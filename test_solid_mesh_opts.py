"""3D FEA, advanced mesh options (step 1): linear (4-node) and quadratic (10-node) tetrahedra with known answers, minimum size, growth rate, refinement
at curved surfaces, a smaller size on single faces (also on split patches), the mesh quality report, the cache key, save / open, and the panel."""
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import solid_geom as sg, solid_fem as fem, solid_model as sm, solid_mesh as smesh

# ------------------------------------------------------------------------------------------------ the quality measure itself
n = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], float)
r = smesh.quality({"nodes": n, "tets": np.array([[0, 2, 1, 3]]), "order": 1})
assert r["inverted"] == 0 and abs(r["ratio_min"] - 1) < 1e-9 and abs(r["dihedral_min"] - 70.5288) < 1e-3 and smesh.verdict(r) == "good", r
assert smesh.quality({"nodes": n, "tets": np.array([[0, 1, 2, 3]])})["inverted"] == 1
flat = np.array([[1, 1, 0], [1, -1, 0], [-1, 1, 0], [0, 0, 1e-4]], float)
rf = smesh.quality({"nodes": flat, "tets": np.array([[0, 1, 2, 3]])})
assert rf["ratio_min"] < 0.01 and smesh.verdict(rf) == "poor"
# options: defaults, validation
d = smesh.default_mesh()
assert d == {"advanced": False, "type": "tets", "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 10, "face_sizes": [], "follows": "patches"}
assert smesh.complete(None) == d and smesh.complete({"order": 1})["growth"] == 1.3
assert smesh.validate(dict(d, growth=1.0), 5.0) and smesh.validate(dict(d, order=3), 5.0) and smesh.validate(dict(d, curv=2), 5.0)
assert smesh.validate(dict(d, hmin=6.0), 5.0) and smesh.validate(d, 5.0) is None
assert smesh.validate(dict(d, face_sizes=[{"face": {}, "h": 6.0}]), 5.0), "a local size larger than the element size is refused"
assert smesh.validate(dict(d, hmin=1.0, face_sizes=[{"face": {}, "h": 0.5}]), 5.0), "and one below the minimum size"
assert smesh.key_text(None) == "" and smesh.options({"mesh": dict(d, order=1)})["order"] == 2, "options off: the plain automatic ones"

# ------------------------------------------------------------------------------------------------ a bar: tension is exact for both orders
solid = b.Solid.make_box(100, 10, 10)
g = sg.analyze(solid)
def face_at(axis, side):
    nn = np.zeros(3); nn[axis] = side
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], nn) > 0.99)
xm, xp, ym, zm = face_at(0, -1), face_at(0, 1), face_at(1, -1), face_at(2, -1)
E_, A, L = 200000.0, 100.0, 100.0

def bar_setup(h, order=2, loads=None, supports=None, **mesh):
    s = sm.default_setup()
    s["h"] = h
    s["supports"] = supports or [{"mode": "fixed", "faces": [sg.face_sig(g, xm)]}]
    s["loads"] = loads or [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [0.0, 0.0, -100.0]}]
    s["mesh"] = dict(smesh.default_mesh(), advanced=True, order=order, **mesh)
    return s

sym = [{"mode": "slide", "faces": [sg.face_sig(g, xm)]}, {"mode": "slide", "faces": [sg.face_sig(g, ym)]}, {"mode": "slide", "faces": [sg.face_sig(g, zm)]}]
pull = [{"kind": "force", "faces": [sg.face_sig(g, xp)], "f": [1000.0, 0.0, 0.0]}]
cache = {}
for order in (2, 1):
    s = bar_setup(5.0, order, pull, sym)
    res = sm.run(g, sm.resolve(g, s), cache)
    assert res["order"] == order and res["u"].shape[0] == res["n_nodes"]
    assert res["n_nodes"] == len(res["nodes"]) and res["conn"].shape[1] == (10 if order == 2 else 4), res["conn"].shape
    assert abs(res["u"][:, 0].max() - 1000 * L / (A * E_)) / (1000 * L / (A * E_)) < 1e-6, (order, res["u"][:, 0].max())     # F L / (A E)
    assert np.allclose(res["vm_el"], 10.0, rtol=1e-6), (order, res["vm_el"].min(), res["vm_el"].max())      # constant strain: exact, element by element
    assert res["equilibrium"] < 1e-9 and abs(res["reaction"][0] + 1000) < 1e-6, (order, res["equilibrium"], res["reaction"])
    assert abs(res["volume"] - 10000) < 1e-6
    q = cache[next(k for k in cache if ("|o1" in k) == (order == 1))]
    assert q["order"] == order and q["quality"]["elements"] == res["n_tets"]
assert len(cache) == 2, "the two orders are two meshes (quadratic with the default options is the plain automatic mesh)"
# the same setup with the options off is the plain automatic mesh: quadratic, and its cache key is the old one
s = bar_setup(5.0, 1, pull, sym); s["mesh"]["advanced"] = False
res = sm.run(g, sm.resolve(g, s), cache)
assert res["order"] == 2 and len(cache) == 2, "options off: quadratic, and the existing cache entry is reused"
assert sm.mesh_key(g, 5.0) in cache and sm.mesh_key(g, 5.0, None) == sm.mesh_key(g, 5.0)

# pressure, gravity, a point force: equilibrium with linear tetrahedra too
for loads, comp, val in (([{"kind": "pressure", "faces": [sg.face_sig(g, xp)], "p": 10.0}], 0, 1000.0),
                         ([{"kind": "gravity", "g": 9.81, "dir": [0, 0, -1]}], 2, 10000 * 7850e-9 * 9.81),
                         ([{"kind": "point", "vertex": sg.vert_sig(g, int(np.argmax([v[0] + v[1] + v[2] for v in g["verts"]]))), "f": [0, 0, -50.0]}], 2, 50.0)):
    res = sm.run(g, sm.resolve(g, bar_setup(5.0, 1, loads)), cache)
    assert abs(abs(res["reaction"][comp]) - val) / val < 1e-6 and res["equilibrium"] < 1e-9, (loads[0]["kind"], res["reaction"], val)

# ------------------------------------------------------------------------------------------------ a cantilever: quadratic is accurate, linear is stiff and converges
beam = 100.0 * 100 ** 3 / (3 * E_ * (10 * 10 ** 3 / 12.0))                  # 0.2 mm
tip = {}
for order, h in ((2, 3.0), (1, 3.0), (1, 2.0), (1, 1.25)):
    res = sm.run(g, sm.resolve(g, bar_setup(h, order)), cache)
    tip[(order, h)] = abs(res["u"][:, 2].min())
    print("cantilever", order, h, res["n_tets"], "tets", tip[(order, h)], "beam theory", beam)
e10 = abs(tip[(2, 3.0)] - beam) / beam
e4 = abs(tip[(1, 3.0)] - beam) / beam
assert e10 < 0.08, ("quadratic, as in the existing test", e10)
assert tip[(1, 3.0)] < tip[(2, 3.0)] and e4 > 2 * e10, ("linear tetrahedra lock in bending: clearly stiffer", e4, e10)
assert tip[(1, 3.0)] < tip[(1, 2.0)] < tip[(1, 1.25)] < beam * 1.05, "linear: finer meshes come closer to beam theory"
assert abs(tip[(1, 1.25)] - beam) / beam < abs(tip[(1, 3.0)] - beam) / beam

# ------------------------------------------------------------------------------------------------ the mesh options reach gmsh
def mesh(h, **opt):
    s = bar_setup(h, **opt)
    r_ = sm.resolve(g, s)
    return sm.get_mesh(g, h, {}, lambda: False, lambda t: None, r_["mesh"])
base = mesh(5.0)
fx = {"face": sg.face_sig(g, xp), "h": 1.5}
loc = mesh(5.0, face_sizes=[fx])
ntri = lambda q_, fid: len(q_["faces"][fid])
assert ntri(loc, xp) > 6 * ntri(base, xp), ("the refined face has many more triangles", ntri(loc, xp), ntri(base, xp))
assert ntri(loc, xm) <= 1.6 * ntri(base, xm), "the far face is not refined"
# the refinement grows away from the face: the elements near it are smaller than the ones far away
def edge_near(q_, x0, w=8.0):
    c = q_["nodes"][q_["tets"]].mean(axis=1)
    sel = np.abs(c[:, 0] - x0) < w
    e = np.linalg.norm(q_["nodes"][q_["tets"][:, 0]] - q_["nodes"][q_["tets"][:, 1]], axis=1)
    return float(e[sel].mean())
assert edge_near(loc, 100.0) < 0.6 * edge_near(loc, 0.0), (edge_near(loc, 100.0), edge_near(loc, 0.0))
# growth rate: a slower growth keeps the small elements over a longer distance = more elements
slow = mesh(5.0, face_sizes=[fx], growth=1.1)
fast = mesh(5.0, face_sizes=[fx], growth=2.0)
assert len(slow["tets"]) > len(fast["tets"]), (len(slow["tets"]), len(fast["tets"]))
assert smesh.quality(loc)["inverted"] == 0 and smesh.quality(loc)["ratio_min"] > 0.02, smesh.quality(loc)
# order 1 and local sizes together; the boundary faces still match the elements
lin = mesh(5.0, order=1, face_sizes=[fx])
assert lin["order"] == 1 and lin["conn"].shape[1] == 4 and len(lin["nodes"]) < len(loc["nodes"])
# a curved part: a block with a hole; minimum size and curvature refinement
hole = b.Box(60, 40, 10, align=(b.Align.MIN, b.Align.MIN, b.Align.MIN)).solid() if False else None
blk = b.Solid.make_box(60, 40, 10)
cyl = b.Solid.make_cylinder(8, 10, b.Plane.XY.offset(0).move(b.Location((30, 20, 0)))) if hasattr(b.Solid, "make_cylinder") else None
if cyl is not None:
    part = blk.cut(cyl)
    gh = sg.analyze(part)
    sh = sm.default_setup(); sh["h"] = 8.0
    sh["supports"] = []; sh["loads"] = []
    def hmesh(**opt):
        s_ = dict(sh); s_["mesh"] = dict(smesh.default_mesh(), advanced=True, **opt)
        return sm.get_mesh(gh, 8.0, {}, lambda: False, lambda t: None, smesh.resolve(gh, s_, 8.0))
    plain = hmesh()
    nocurv = hmesh(curv=0)
    fine = hmesh(curv=30)
    fine_min = hmesh(curv=30, hmin=3.0)
    assert len(nocurv["tets"]) < len(plain["tets"]) < len(fine["tets"]), ("refinement at the hole", len(nocurv["tets"]), len(plain["tets"]), len(fine["tets"]))
    # the minimum size stops the curvature refinement from making elements smaller than it asks for (30 elements around r = 8: 1.7 mm)
    assert len(fine_min["tets"]) < 0.5 * len(fine["tets"]), (len(fine_min["tets"]), len(fine["tets"]))
    assert smesh.quality(fine_min)["edge_min"] > smesh.quality(fine)["edge_min"]
    print("hole", len(nocurv["tets"]), len(plain["tets"]), len(fine["tets"]), len(fine_min["tets"]))

# ------------------------------------------------------------------------------------------------ a lost face is an error naming the local size
bad = bar_setup(5.0, face_sizes=[{"face": dict(sg.face_sig(g, xp), normal=[0.0, 0.0, 1.0], center=[1e6, 1e6, 1e6]), "h": 1.0}])
try:
    sm.resolve(g, bad); raise SystemExit("a face that is not in the part must be an error")
except fem.FemError as ex:
    assert "Local size 1" in str(ex), ex
try:
    sm.resolve(g, bar_setup(5.0, growth=0.5)); raise SystemExit("growth below 1 is refused")
except fem.FemError as ex:
    assert "growth" in str(ex).lower(), ex

# ------------------------------------------------------------------------------------------------ the window
import pm_model as pmod, sk_tools as sk
import solid_tab
T = tempfile.mkdtemp(prefix="opara_mo_")
d_ = pmod.Document(); d_.params = {"T": "10"}
s_ = d_.add(pmod.new_feature("sketch", plane={"base": "Top"})); d_.rebuild(); m_ = d_.models[s_["id"]]
rr = sk.add_rect_corner(m_, (0, 0), (100, 10))
m_.add_con("dim_h", [("ln", rr["lns"][0])], value=100.0); m_.add_con("dim_v", [("ln", rr["lns"][1])], value=10.0)
sk.solve_model(m_); d_.store_sketch(s_["id"])
d_.add(pmod.new_feature("extrude", sketch=s_["id"], depth="T")); d_.rebuild()
part_file = os.path.join(T, "bar.gpd"); open(part_file, "w").write(d_.to_json())
w = solid_tab.SolidWindow(threaded=False)
w.resize(1300, 1700); w.show()
assert w.create_project(os.path.join(T, "bar_mo")) and w.import_file(part_file), MSGS
mesh_sec = next(x for x in w.sections if x.title == "Mesh")
assert mesh_sec.isAncestorOf(w.cb_adv) and w.cb_adv.text() == "Advanced mesh options" and not w.cb_adv.isChecked()
assert not w.adv_box.isVisibleTo(w), "the options are hidden until the box is ticked"
w.cb_adv.setChecked(True); app.processEvents()
assert w.adv_box.isVisibleTo(w) and mesh_sec.isAncestorOf(w.adv_box)
# what is offered: element order, manual refinement, quality, what the mesh follows - nothing grey about the future
assert [w.order_combo.itemData(i) for i in range(w.order_combo.count())] == [2, 1] and w.order_combo.currentData() == 2
assert w.follows_combo.count() == 1 and w.follows_combo.currentData() == "patches" and w.follows_combo.isEnabled()
for wid in (w.e_hmin, w.e_growth, w.cb_curv, w.sp_curv, w.face_table, w.e_face_h, w.b_face_size, w.b_face_size_del, w.follows_combo, w.order_combo):
    assert mesh_sec.isAncestorOf(wid) and w.adv_box.isAncestorOf(wid), wid
assert mesh_sec.isAncestorOf(w.quality_lbl) and not w.quality_box.isVisibleTo(w), "the quality report is under the Mesh button, after a mesh was made"
assert w.e_growth.text() == "1.3" and w.cb_curv.isChecked() and w.sp_curv.value() == 10 and w.e_hmin.text() == ""
# a fixed end and a pull
def face(nv):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], nv) > 0.99)
w.select_faces([face([-1, 0, 0])]); assert w.add_support("fixed")
w.select_faces([face([1, 0, 0])]); assert w.add_load("force", {"f": [0.0, 0.0, -100.0]})
w.e_h.setText("3"); w.inputs_changed()
# options are read into the setup
w.order_combo.setCurrentIndex(w.order_combo.findData(1)); w.order_combo.activated.emit(w.order_combo.currentIndex())
assert w.setup["mesh"]["advanced"] is True and w.setup["mesh"]["order"] == 1
assert w.run_mesh() and w.mesh_q["order"] == 1 and "linear" in w.mesh_lbl.text().lower(), w.mesh_lbl.text()
assert "radius ratio" in w.quality_lbl.text().lower() and f"{w.mesh_q['quality']['elements']:,}" in w.quality_lbl.text(), w.quality_lbl.text()
assert w.quality_box.isVisibleTo(w) and "linear" in w.quality_lbl.text()
w.cb_adv.setChecked(False); app.processEvents()
assert not w.quality_box.isVisibleTo(w) and not w.adv_box.isVisibleTo(w) and w.setup["mesh"]["advanced"] is False
w.cb_adv.setChecked(True); app.processEvents()
assert w.setup["mesh"]["order"] == 1, "the choices are remembered while the options are off"
assert w.mesh_q is None and not w.quality_box.isVisibleTo(w), "switching the options off and on made another mesh necessary: no stale quality report"
assert w.run_mesh() and w.quality_box.isVisibleTo(w) and "linear" in w.quality_lbl.text(), "a new mesh brings the report back"
assert w.run_solve() and w.result["order"] == 1 and "linear" in w.mesh_lbl.text().lower() and "Tetrahedra (linear)" in w.res_lbl.text(), w.res_lbl.text()
tip_lin = abs(w.result["u"][:, 2].min())
w.order_combo.setCurrentIndex(w.order_combo.findData(2)); w.order_combo.activated.emit(w.order_combo.currentIndex())
assert w.result is None, "a changed mesh option: the old result no longer applies"
assert w.run_solve() and w.result["order"] == 2 and "quadratic" in w.mesh_lbl.text().lower()
tip_quad = abs(w.result["u"][:, 2].min())
assert tip_lin < tip_quad < 0.215 and abs(tip_quad - 0.2) / 0.2 < 0.08, (tip_lin, tip_quad)
# local size on the selected face: set / list / remove
w.select_faces([face([1, 0, 0])])
w.e_face_h.setText("1")
w.b_face_size.click()
assert len(w.setup["mesh"]["face_sizes"]) == 1 and w.setup["mesh"]["face_sizes"][0]["h"] == 1.0 and w.face_table.rowCount() == 1
assert "Face" in w.face_table.item(0, 0).text() and w.face_table.item(0, 1).text() == "1", (w.face_table.item(0, 0).text(), w.face_table.item(0, 1).text())
w.select_faces([face([1, 0, 0])]); w.e_face_h.setText("1.5"); w.b_face_size.click()
assert len(w.setup["mesh"]["face_sizes"]) == 1 and w.setup["mesh"]["face_sizes"][0]["h"] == 1.5, "the same face again changes its size"
w.e_face_h.setText("9"); w.b_face_size.click()
assert w.setup["mesh"]["face_sizes"][0]["h"] == 1.5 and "smaller" in w.status_lbl.text(), (w.status_lbl.text(), "a size that does not refine is refused")
w.e_face_h.setText("abc"); w.b_face_size.click()
assert "number" in w.status_lbl.text() and w.setup["mesh"]["face_sizes"][0]["h"] == 1.5
w.select_faces([]); w.e_face_h.setText("1"); w.b_face_size.click()
assert "Select" in w.status_lbl.text(), w.status_lbl.text()
assert w.run_mesh() and w.mesh_q["faces"][face([1, 0, 0])].shape[0] > 40, w.mesh_q["faces"][face([1, 0, 0])].shape
q1 = w.mesh_q["quality"]
w.face_table.setCurrentCell(0, 0)
w.b_face_size_del.click()
assert w.setup["mesh"]["face_sizes"] == [] and w.face_table.rowCount() == 0
# bad numbers in the boxes: said in the status line, the mesh is not made
w.e_growth.setText("0.9"); w.e_growth.editingFinished.emit()
MSGS.clear()
assert w.run_mesh() is False and "growth" in w.status_lbl.text().lower(), w.status_lbl.text()
w.e_growth.setText("1.3"); w.e_growth.editingFinished.emit()
w.e_hmin.setText("0.5"); w.e_hmin.editingFinished.emit()
assert w.setup["mesh"]["hmin"] == 0.5
w.e_hmin.setText(""); w.e_hmin.editingFinished.emit()
w.cb_curv.setChecked(False); assert w.setup["mesh"]["curv"] == 0 and not w.sp_curv.isEnabled()
w.cb_curv.setChecked(True); assert w.setup["mesh"]["curv"] == 10

# save, close, open: the options come back
w.order_combo.setCurrentIndex(w.order_combo.findData(1)); w.order_combo.activated.emit(w.order_combo.currentIndex())
w.select_faces([face([1, 0, 0])]); w.e_face_h.setText("2"); w.b_face_size.click()
w.e_growth.setText("1.6"); w.e_growth.editingFinished.emit()
w.e_hmin.setText("0.7"); w.e_hmin.editingFinished.emit()
assert w.is_dirty()
assert w.save(), w.status_lbl.text()
assert not w.is_dirty()
folder = w.path
w2 = solid_tab.SolidWindow.open_project(None, folder, threaded=False)
assert w2.setup["mesh"]["advanced"] is True and w2.setup["mesh"]["order"] == 1 and w2.setup["mesh"]["growth"] == 1.6 and w2.setup["mesh"]["hmin"] == 0.7
assert len(w2.setup["mesh"]["face_sizes"]) == 1 and w2.setup["mesh"]["face_sizes"][0]["h"] == 2.0
assert w2.cb_adv.isChecked() and w2.order_combo.currentData() == 1 and w2.e_growth.text() == "1.6" and w2.e_hmin.text() == "0.7" and w2.face_table.rowCount() == 1
assert not w2.is_dirty()
# a project saved before these options existed opens with the defaults
import sim_project as spj
sp_ = spj.state_path(folder)
st = json.load(open(sp_))
st["setup"].pop("mesh")
json.dump(st, open(sp_, "w"))
w3 = solid_tab.SolidWindow.open_project(None, folder, threaded=False)
assert w3.setup.get("mesh") == smesh.default_mesh()
w3.show(); app.processEvents()
assert not w3.cb_adv.isChecked() and w3.order_combo.currentData() == 2 and w3.face_table.rowCount() == 0
# a parametric study keeps working with the options in the setup
w2.import_state(w2.export_state())
assert w2.setup["mesh"]["order"] == 1 and w2.order_combo.currentData() == 1

print("OK solid mesh options")
os._exit(0)
