"""The 3D FEA window with SCREWS: the joint 'Screws and bolts' (parts touch freely), faces between two parts listed and split into patches, ONE screw put on
SEVERAL patches at once, refusals (a support on a joint face, a patch that has a screw, a face that is not between two parts), the solve with its contact and
screw tables, the checks made again when only the screw numbers or the design method change, hiding a part to see the joint faces, markers, remove, save and
reopen, and going back to fully bonded."""
import faulthandler
faulthandler.dump_traceback_later(175, exit=True)
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "addons_src", "parametric"),
                os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, asm_model as am
import solid_tab, solid_geom as sg, solid_screw as screw, solid_view as sv
import std_aisi16
import sim_project as sp

T = tempfile.mkdtemp(prefix="opara_solid_screw_")
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
make_part(os.path.join(ad, "base.gpd"), 30.0, 6.0)                       # steel, 30 x 30 x 6
make_part(os.path.join(ad, "cap.gpd"), 30.0, 4.0, ALU)                   # aluminium, 30 x 30 x 4, on top
a = am.Assembly()
a.add_component("base.gpd", fixed=True, pos=(0, 0, 0))
a.add_component("cap.gpd", fixed=False, pos=(0, 0, 6))
asm = os.path.join(ad, "plates.gpa")
open(asm, "w").write(a.to_json())

w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bolted")) and w.import_file(asm), MSGS
g = w.geom
assert w.is_asm() and w.setup["joint"] == "bonded" and w.setup["screws"] == [] and w.setup["design"] == "ASD"
iface = [f["id"] for f in g["faces"] if f["interface"]]
assert len(iface) == 1 and w.faces.item(iface[0]).isHidden() and not w.screw_box.isVisibleTo(w)
assert w.b_split.isVisibleTo(w) and not w.dims.isVisibleTo(w)                         # the face splits work on an assembly; the part dimensions do not
names = [b["name"] for b in g["bodies"]]
base_i = next(i for i, n in enumerate(names) if "base" in n.lower())
cap_i = 1 - base_i

# ---- the joint: screws and bolts
assert w.set_joint("contact") and w.joint_mode() == "contact" and w.joint_combo.currentData() == "contact"
assert w.screw_box.isVisibleTo(w) and not w.faces.item(iface[0]).isHidden() and "joint face" in w.face_label(iface[0]), w.face_label(iface[0])
assert w.show_list.count() == 2 and w.screw_table.rowCount() == 0 and not w.b_edit_screw.isEnabled()


def outer_faces():
    """(bottom of the base, +x side of the cap) in the geometry now (the numbers of the faces change when a face is split)."""
    gg = w.geom
    return (next(f["id"] for f in gg["faces"] if not f["interface"] and f["normal"][2] < -0.99),
            next(f["id"] for f in gg["faces"] if not f["interface"] and f["normal"][0] > 0.99 and f["body"] == cap_i))


bottom, sidef = outer_faces()

# a face between two parts is inside: no support, no load there
w.select_faces(iface)
assert not w.add_support("fixed") and "inside the assembly" in w.status_lbl.text()
assert not w.add_load("force", {"f": [1.0, 0.0, 0.0]}) and "inside the assembly" in w.status_lbl.text()
assert w.setup["supports"] == [] and w.setup["loads"] == []

# ---- cut the joint face into patches with the split tool (2 x 2 first)
w.select_faces(iface)
w.sp_cols.setValue(2); w.sp_rows.setValue(2)
assert w.split_selected(), w.status_lbl.text()
g = w.geom
bottom, sidef = outer_faces()
cells = {f["cell"]: f["id"] for f in g["faces"] if f["interface"]}
assert sorted(cells) == [(0, 0), (0, 1), (1, 0), (1, 1)] and all(abs(g["faces"][i]["area"] - 225.0) < 1e-6 for i in cells.values()), cells
assert "column 2 row 1" in w.face_label(cells[(1, 0)]) and "joint face" in w.face_label(cells[(1, 0)])

# ---- add the same screw to several patches at once; refusals
vals = dict(screw.default_screw(), Pnvs=3000.0, Pnts=2500.0, length=8.0)              # an 8 mm screw: 4 mm cap on 6 mm base: reaches 4 mm into the base
w.select_faces([])
assert not w.add_screws(values=vals) and "Select the patch" in w.status_lbl.text()
w.select_faces([bottom])
assert not w.add_screws(values=vals) and "between two parts" in w.status_lbl.text()
w.select_faces([cells[(0, 0)], cells[(1, 1)]])
assert w.add_screws(values=vals), w.status_lbl.text()
sc0 = w.setup["screws"][0]
assert len(w.setup["screws"]) == 1 and len(sc0["faces"]) == 2 and sc0["name"] == "Screw 1" and sc0["length"] == 8.0
assert w.screw_table.rowCount() == 1 and w.screw_table.item(0, 3).text() == "2" and w.screw_table.item(0, 1).text() == "Screw"
w.select_faces([cells[(0, 0)]])
assert not w.add_screws(values=vals) and "already has a screw" in w.status_lbl.text()
bolt = dict(screw.default_screw("bolt"), Fnv=372.0, Fnt=620.0, planes=1)
w.select_faces([cells[(0, 1)], cells[(1, 0)]])
assert w.add_screws(values=bolt) and w.setup["screws"][1]["name"] == "Bolt 1" and w.setup["screws"][1]["kind"] == "bolt"
assert w.screw_table.rowCount() == 2 and "Bolt" in w.screw_table.item(1, 1).text()
# selecting a row of the table selects its patches
w.screw_table.selectRow(0)
assert sorted(w.sel_faces) == sorted([cells[(0, 0)], cells[(1, 1)]])
assert len(w.view.marker_data) == 4                                                    # a marker on each of the four patches

# ---- the window that asks for the numbers (it is accepted without showing it)
real_exec = QDialog.exec


def fake_exec(self):
    combos = self.findChildren(QComboBox)
    edits = self.findChildren(QLineEdit)
    combos[0].setCurrentIndex(1)                                                       # Type: Bolt (its usual numbers come in)
    return 1


QDialog.exec = fake_exec
got = w.ask_screw(None, 3)
assert got["kind"] == "bolt" and abs(got["d"] - 12.0) < 1e-5 and got["planes"] == 1 and "length" not in got, got
QDialog.exec = lambda self: 1
got = w.ask_screw(None, 1)
assert got["kind"] == "screw" and abs(got["d"] - 4.8) < 1e-5 and abs(got["length"] - 25.0) < 1e-5 and got["head"] == "thin" and abs(got["dh"] - 9.5) < 1e-5, got
QDialog.exec = lambda self: 0
assert w.ask_screw(None, 1) is None
QDialog.exec = real_exec

# ---- supports, load, mesh and solve
w.select_faces([bottom]); assert w.add_support("fixed")
w.select_faces([sidef]); assert w.add_load("force", {"f": [600.0, 0.0, 0.0]})
w.e_h.setText("4"); w.inputs_changed()
assert w.ready() is None, w.ready()
assert w.run_mesh() and "tetrahedra" in w.mesh_lbl.text(), w.status_lbl.text()
assert w.run_solve() and w.result is not None, w.status_lbl.text()
res = w.result
assert res["joint"] == "contact" and res["equilibrium"] < 1e-6 and res["contact"]["converged"], (res["equilibrium"], res["contact"])
assert len(res["screws"]) == 4 and {r_["screw"] for r_ in res["screws"]} == {"Screw 1", "Bolt 1"}
Fx = sum(r_["F"][0] for r_ in res["screws"])
assert abs(Fx + 600.0) < 1e-6, Fx                                                       # the four fasteners carry the whole load in shear (exact)
txt = w.res_lbl.text()
assert "Screws and bolts" in txt and "AISI S100-16" in txt and "Contact between the parts" in txt and "joined by screws" in txt and "Bodies (fully bonded)" not in txt
assert w.screw_table.item(0, 4).text() != "" and w.screw_table.item(1, 4).text() != "", [w.screw_table.item(i, 4).text() for i in range(2)]
st = {r_["fid"]: r_["status"] for r_ in res["screws"]}
assert len(w.view.marker_data) == 4 and all(tuple(c) in {tuple(0.55 * y for y in x) for x in sv.STATUS_RGB.values()} for _p, c in w.view.marker_data)
s_sc = [r_ for r_ in res["screws"] if r_["screw"] == "Screw 1"][0]
assert not s_sc["through"] and abs(s_sc["reach"] - 4.0) < 1e-6 and abs(s_sc["t1"] - 4.0) < 1e-6 and abs(s_sc["t2"] - 6.0) < 1e-6, (s_sc["t1"], s_sc["t2"], s_sc["reach"])
assert abs(s_sc["tc"] - 4.0) < 1e-6                                                     # the 8 mm screw holds with 4 mm of thread in the 6 mm base
print("solve ok", [round(r_["V"], 1) for r_ in res["screws"]], res["contact"]["iterations"])

# ---- only the numbers changed: checked again from the forces, no new solution
before = {r_["fid"]: r_["V"] for r_ in res["screws"]}
assert w.edit_screw(0, values=dict(vals, Pnvs=90000.0, name="Screw 1"))
assert w.result is res and not w.res_lbl.text().startswith("The setup changed")
r1 = [r_ for r_ in w.result["screws"] if r_["screw"] == "Screw 1"][0]
c1 = {c["clause"]: c for c in r1["checks"]}
f432 = next(f for f in std_aisi16.SCREW_FUNCS if f.name == "J4_3_2")
cap432 = screw._call(f432.impl, "ASD", Pnvs=90000.0 / screw.LBF_N) * screw.LBF_N
assert c1["J4.3.2"]["applies"] and abs(c1["J4.3.2"]["capacity"] - cap432) < 1e-9 * cap432 and abs(c1["J4.3.2"]["ratio"] - r1["V"] / cap432) < 1e-9, (c1["J4.3.2"], cap432)
assert {r_["fid"]: r_["V"] for r_ in w.result["screws"]} == before                      # the forces are those of the solve
assert w.set_design("LRFD") and w.result is res and all(r_["method"] == "LRFD" for r_ in w.result["screws"]) and "LRFD" in w.res_lbl.text()
assert w.design_combo.currentData() == "LRFD"
w.set_design("ASD")

# ---- hide a part: the faces between it and the part that stays are drawn and can be clicked; one part always stays
nt = len(w.result["conn"])
w.set_hidden_bodies({cap_i})
nb = len(w.shown_cells())
assert 0 < nb < nt and nb == int((w.result["tet_body"] != cap_i).sum()), (nb, nt)           # the result view leaves the hidden part out
P, Tr, F = sg.display_mesh(w.geom, w.hidden_bodies)
assert set(cells.values()) <= set(np.unique(F)) and w.show_list.item(cap_i).checkState().value == 0
w.set_hidden_bodies({0, 1})
assert len(w.hidden_bodies) == 1 and "stays" in w.status_lbl.text()
w.set_hidden_bodies(set())
assert len(w.shown_cells()) == nt
P, Tr, F = sg.display_mesh(w.geom, w.hidden_bodies)
assert not (set(cells.values()) & set(np.unique(F)))

# ---- remove one: the result goes (the patches changed), the markers follow
assert w.remove_screw(1) and len(w.setup["screws"]) == 1 and w.result is None and w.res_lbl.text().startswith("The setup changed")
assert len(w.view.marker_data) == 2 and w.screw_table.rowCount() == 1

# ---- save and reopen
w.save()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w2.setup["joint"] == "contact" and len(w2.setup["screws"]) == 1 and len(w2.setup["screws"][0]["faces"]) == 2 and w2.joint_combo.currentData() == "contact"
ifs2 = [f["id"] for f in w2.geom["faces"] if f["interface"]]
assert w2.screw_box.isVisibleTo(w2) and w2.screw_table.rowCount() == 1 and ifs2 and all(not w2.faces.item(i).isHidden() for i in ifs2) and w2.ready() is None
assert len(w2.view.marker_data) == 2
print("reopen ok")

# ---- the same fastener on many patches: split 3 x 3 and put one screw on six of them
w.select_faces(list(cells.values()))
assert w.split_selected(3, 3), w.status_lbl.text()
bottom, sidef = outer_faces()
cells3 = {f["cell"]: f["id"] for f in w.geom["faces"] if f["interface"]}
assert len(cells3) == 9 and w.setup["screws"] == [], w.setup["screws"]                  # the patches of the old split are gone with their screws
six = [cells3[c] for c in ((0, 0), (1, 0), (2, 0), (0, 2), (1, 2), (2, 2))]
w.select_faces(six)
assert w.add_screws(values=dict(screw.default_screw(), length=10.0)) and len(w.setup["screws"]) == 1 and len(w.setup["screws"][0]["faces"]) == 6
assert w.screw_table.item(0, 3).text() == "6" and len(w.view.marker_data) == 6
assert len(w.setup["supports"]) == 1 and len(w.setup["loads"]) == 1                      # the support and the load found their faces again after the new split
w.setup["loads"][0]["f"] = [900.0, 0.0, 0.0]
assert w.ready() is None, w.ready()
assert w.run_solve(), w.status_lbl.text()
assert len(w.result["screws"]) == 6, len(w.result["screws"])
assert abs(sum(r_["F"][0] for r_ in w.result["screws"]) + 900.0) < 1e-6, [r_["F"] for r_ in w.result["screws"]]
assert True and abs(sum(r_["F"][0] for r_ in w.result["screws"]) + 900.0) < 1e-6
assert w.res_lbl.text().count("Screw 1 at") >= 6                                       # one line for each of the six patches
print("six patches ok", [round(r_["V"], 1) for r_ in w.result["screws"]])

# ---- back to fully bonded: the joint faces are not listed, the screws are kept but not used, and the bonded solve works on the split faces
ifs = [f["id"] for f in w.geom["faces"] if f["interface"]]
assert w.set_joint("bonded") and all(w.faces.item(i).isHidden() for i in ifs) and not w.screw_box.isVisibleTo(w) and len(w.setup["screws"]) == 1
assert w.result is None and w.ready() is None
assert w.run_solve() and w.result["joint"] == "bonded" and not w.result.get("screws") and "Bodies (fully bonded)" in w.res_lbl.text()
print("all ok")
