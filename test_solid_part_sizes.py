"""3D FEA: an element size for every PART of an assembly (the Element size box is now a table: one row per part, a single part has one row).

Model (no window): the sizes of the parts go into ONE mesh, so the faces two parts share keep matching nodes (the bonded joint: the same nodes) - the face
gets the finer of the two sizes and the coarser part grows away from it; a size that equals the default changes nothing (same cache key); the checks
(minimum size, local sizes, thin parts); the progress estimate.
Window: the table (auto text, typing, bad numbers, clearing, element counts after meshing), save and reopen, a project saved with one size for all parts,
the studies' element size, units, local sizes on parts of different sizes, the thin-part mark."""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import os, sys, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm, solid_asm as sa, solid_mesh as smesh, solid_progress as spg

STEEL = {"name": "Steel", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.3, "Sy_MPa": 250.0, "Su_MPa": 400.0}
ALU = {"name": "Aluminium", "density": 2700.0, "E_MPa": 70000.0, "nu": 0.33, "Sy_MPa": 100.0, "Su_MPa": 200.0}


def box(x0, x1, y0, y1, z0, z1):
    return b.Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * b.Box(x1 - x0, y1 - y0, z1 - z0)


def get_mesh(g, st):
    r = sm.resolve(g, st)
    return r, sm.get_mesh(g, r["h"] or sm.auto_h(g), {}, lambda: False, lambda t: None, r["mesh"])


def mean_edge(q, body):
    c = np.vstack([x["conn"][:, :4] for x in q["groups"] if x["body"] == body])
    p = q["nodes"][c]
    e = [np.linalg.norm(p[:, i] - p[:, j], axis=1) for i in range(4) for j in range(i + 1, 4)]
    return float(np.mean(e))


def n_of(q, body):
    return sum(len(x["conn"]) for x in q["groups"] if x["body"] == body)


# ---------------------------------------------------------------------------------------------------------------- the model: a plate bonded on a base
BASE, PLATE = box(0, 60, 0, 60, 0, 20), box(20, 40, 20, 40, 20, 26)
g = sa.analyze_assembly([("Base", BASE, STEEL), ("Plate", PLATE, STEEL)])
assert [x["name"] for x in g["bodies"]] == ["Base", "Plate"] and len(g["solids"]) == 2
iface = next(f["id"] for f in g["faces"] if f["interface"])
bottom = next(f["id"] for f in g["faces"] if not f["interface"] and f["normal"][2] < -0.99)
top = next(f["id"] for f in g["faces"] if not f["interface"] and f["normal"][2] > 0.99 and f["body"] == 1)


def setup(h, body_h, load=(0.0, 0.0, -1000.0)):
    st = sm.default_setup()
    st["h"], st["body_h"] = h, dict(body_h)
    st["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, bottom)]}]
    st["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, top)], "f": list(load)}]
    return st


# the sizes as the mesher gets them
assert smesh.body_sizes(g, {"body_h": {"Plate": 1.5}}, 4.0) == {1: 1.5}
assert smesh.body_sizes(g, {"body_h": {"Plate": 4.0}}, 4.0) == {}, "a size that is the default anyway is not a size of its own"
assert smesh.body_sizes(g, {"body_h": {"Plate": 0.0, "Base": ""}}, 4.0) == {}, "0 and blank are the automatic size"
assert smesh.body_sizes(g, {"body_h": {"Nobody": 2.0}}, 4.0) == {}, "a name that is not in the assembly is ignored"
assert smesh.body_sizes(g, {}, 4.0) == {} and smesh.body_sizes({"faces": []}, {"body_h": {"Plate": 1.0}}, 4.0) == {}
for bad in (-1.0, "x"):
    try:
        smesh.body_sizes(g, {"body_h": {"Plate": bad}}, 4.0)
        raise AssertionError("a bad size must be refused")
    except fem.FemError as ex:
        assert "Plate" in str(ex)
assert fem.element_sizes(g, 4.0, {"body_h": {1: 1.5}}) == [4.0, 1.5] and fem.element_sizes(g, 4.0, None) == [4.0, 4.0]
assert fem.element_sizes({"faces": []}, 4.0, {"body_h": {1: 1.5}}) == [4.0], "a single part has the one size"

# the options: nothing but a plain mesh when there are no sizes of their own; the cache key tells the sizes apart
assert smesh.resolve(g, setup(4.0, {}), 4.0) is None and smesh.key_text(None) == ""
o1 = smesh.resolve(g, setup(4.0, {"Plate": 1.5}), 4.0)
assert o1 is not None and o1["body_h"] == {1: 1.5} and o1["order"] == 2 and o1["curv"] == 10 and o1["face_sizes"] == [] and o1["type"] == "tets"
o2 = smesh.resolve(g, setup(4.0, {"Plate": 2.0}), 4.0)
assert smesh.key_text(o1) != smesh.key_text(o2) and smesh.key_text(o1) != "" and smesh.key_text(o1) == smesh.key_text(smesh.resolve(g, setup(4.0, {"Plate": 1.5}), 4.0))
assert sm.mesh_key(g, 4.0, o1) != sm.mesh_key(g, 4.0, None) and sm.mesh_key(g, 4.0, o1) != sm.mesh_key(g, 4.0, o2)
assert smesh.resolve(g, setup(4.0, {"Plate": 4.0, "Base": 4.0}), 4.0) is None, "every size is the default: the plain mesh, the plain key"

# the checks: the minimum size against the smallest part, a local size against the size of ITS part
st = setup(8.0, {"Plate": 1.5})
st["mesh"] = dict(smesh.complete(None), advanced=True, hmin=2.0)
try:
    sm.resolve(g, st)
    raise AssertionError("the minimum size 2 is above the plate's size 1.5")
except fem.FemError as ex:
    assert "minimum" in str(ex).lower()
st["mesh"] = dict(smesh.complete(None), advanced=True, hmin=0.5, face_sizes=[{"face": sg.face_sig(g, bottom), "h": 5.0}])
r = sm.resolve(g, st)                                                         # 5 mm on the base's own bottom face: smaller than the base's 8, fine
assert r["mesh"]["face_sizes"][0]["h"] == 5.0 and r["mesh"]["body_h"] == {1: 1.5}
st["mesh"]["face_sizes"] = [{"face": sg.face_sig(g, bottom), "h": 9.0}]
try:
    sm.resolve(g, st)
    raise AssertionError("a local size above the size of its part")
except fem.FemError as ex:
    assert "smaller" in str(ex)
st["mesh"]["face_sizes"] = [{"face": sg.face_sig(g, top), "h": 2.0}]           # the plate's top: the plate's size is 1.5
try:
    sm.resolve(g, st)
    raise AssertionError("2 is above the plate's 1.5")
except fem.FemError:
    pass
refs = smesh.face_refs(g, [[bottom], [top], [iface]], {1: 1.5}, 8.0)
assert refs == [8.0, 1.5, 1.5], refs                                           # the face between the parts: the finer size

# ---- the mesh: ONE mesh whose parts have their own sizes; the shared face keeps shared nodes
r, q = get_mesh(g, setup(4.0, {}))
n4 = (n_of(q, 0), n_of(q, 1))
r, qm = get_mesh(g, setup(8.0, {"Plate": 1.5}))
assert qm["tet_body"] is not None and len(qm["groups"]) == 2 and qm["order"] == 2
nb, npl = n_of(qm, 0), n_of(qm, 1)
assert npl > 8 * n4[1], (npl, n4)                                              # the plate is far finer than at 4 mm ...
assert nb < n4[0], (nb, n4)                                                    # ... and the base is coarser than at 4 mm (8 mm away from the plate)
assert mean_edge(qm, 1) < 0.5 * mean_edge(qm, 0), (mean_edge(qm, 1), mean_edge(qm, 0))
nodes_iface = set(np.unique(qm["faces"][iface]))
for grp in qm["groups"]:
    assert nodes_iface <= set(np.unique(grp["conn"][:, :4])), "every node of the shared face belongs to both parts: the mesh is conforming"
assert len(nodes_iface) > 100, len(nodes_iface)                                # the shared face is meshed as fine as the plate (20 x 20 mm at 1.5 mm)
qa = smesh.quality(qm)
assert qa["ratio_min"] > 0.05 and qa["elements"] == nb + npl, qa["ratio_min"]
print("mesh ok: base", nb, "plate", npl, "(uniform 4 mm:", n4, ") shared-face nodes", len(nodes_iface), "worst ratio", round(qa["ratio_min"], 2))

# the other way round: a fine base under a coarse plate - the shared face has the base's (finer) size
r, qr = get_mesh(g, setup(3.0, {"Plate": 8.0}))
assert mean_edge(qr, 0) < 4.0 and mean_edge(qr, 1) < 4.5 and len(set(np.unique(qr["faces"][iface]))) > 60
for grp in qr["groups"]:
    assert set(np.unique(qr["faces"][iface])) <= set(np.unique(grp["conn"][:, :4]))

# ---- the answer does not depend on the sizes (a stack of two bars: the extension is known)
G2 = sa.analyze_assembly([("Base", box(-10, 10, -10, 10, 0, 30), STEEL), ("Block", box(-10, 10, -10, 10, 30, 50), ALU)])
bot2 = next(f["id"] for f in G2["faces"] if not f["interface"] and f["normal"][2] < -0.99)
top2 = next(f["id"] for f in G2["faces"] if not f["interface"] and f["normal"][2] > 0.99)
want = 10000.0 * (30 / 200000.0 + 20 / 70000.0) / 400.0
for sizes in ({}, {"Base": 9.0, "Block": 4.0}, {"Base": 4.0, "Block": 9.0}):
    s2 = sm.default_setup()
    s2["h"], s2["body_h"] = 6.0, sizes
    s2["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(G2, bot2)]}]
    s2["loads"] = [{"kind": "force", "faces": [sg.face_sig(G2, top2)], "f": [0.0, 0.0, -10000.0]}]
    res = sm.run(G2, sm.resolve(G2, s2), {})
    assert abs(res["umax"] - want) / want < 0.05 and res["equilibrium"] < 1e-6 and abs(res["reaction"][2] - 10000.0) < 1e-3, (sizes, res["umax"], want)
    assert [p["name"] for p in res["part_sizes"]] == ["Base", "Block"] and [p["h"] for p in res["part_sizes"]] == [sizes.get("Base", 6.0), sizes.get("Block", 6.0)]
print("series ok (the stack's answer is the same for different sizes)")

# ---- the thin-part check and the progress estimate follow the sizes of the parts
THIN = sa.analyze_assembly([("Block", box(0, 40, 0, 40, 0, 40), STEEL), ("Sheet", box(0, 40, 0, 40, 40, 42), STEEL)])
assert sm.thin_parts(THIN, 6.0, [6.0, 6.0]).keys() == {1} and sm.thin_parts(THIN, 6.0, [6.0, 1.0]) == {} and len(sm.thin_notes(THIN, 6.0, [6.0, 6.0])) == 1
assert "Sheet" in sm.thin_notes(THIN, 6.0, [6.0, 6.0])[0] and "its element size is 6" in sm.thin_notes(THIN, 6.0, [6.0, 6.0])[0]
e0 = spg.estimate_for(g, 8.0, None)
e1 = spg.estimate_for(g, 8.0, {1: 1.5})
assert abs(e0 - spg.estimate_elements(g["volume"], 8.0)) < 1e-6 and e1 > 5 * e0, (e0, e1)
assert abs(e1 - (spg.estimate_elements(g["bodies"][0]["volume"], 8.0) + spg.estimate_elements(g["bodies"][1]["volume"], 1.5))) < 1e-6
pl = dict(spg.plan_for(g, {"h": 8.0, "mesh": o1}, solving=False))
assert pl["mesh"] > 1000 * 0 and abs(pl["mesh"] - spg.estimate_for(g, 8.0, {1: 1.5})) < 1e-6, pl
print("checks and estimate ok")

# ---------------------------------------------------------------------------------------------------------------- the window
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QColor
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk, asm_model as am
import solid_tab, solid_study
import sim_project as sp

T = tempfile.mkdtemp(prefix="opara_solid_sizes_")


def make_part(path, w, depth, material=None, length=None):
    d = pm.Document()
    d.params = {"H": str(depth)}
    s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s["id"]]
    r_ = sk.add_rect_corner(m, (0, 0), (length or w, w))
    m.add_con("dim_h", [("ln", r_["lns"][0])], value=length or w)
    m.add_con("dim_v", [("ln", r_["lns"][1])], value=w)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth="H"))
    d.rebuild()
    assert d.solid is not None
    if material:
        d.material = material
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())


def make_asm(folder, parts, name):
    a = am.Assembly()
    for i, (p, pos) in enumerate(parts):
        a.add_component(p, fixed=(i == 0), pos=pos)
    path = os.path.join(folder, name)
    open(path, "w").write(a.to_json())
    return path


L = solid_tab.UD()["L"]
assert L == "mm", L

# ---- a single part: one row
pd = os.path.join(T, "single")
os.makedirs(pd)
make_part(os.path.join(pd, "bar.gpd"), 10.0, 10.0, length=100.0)
w = solid_tab.SolidWindow(threaded=False)
assert not hasattr(w, "e_h"), "the Element size box is gone: the size is in the table"
assert w.size_table.rowCount() == 0 and "mm" in w.h_label.text()
assert w.create_project(os.path.join(T, "bar_study")) and w.import_file(os.path.join(pd, "bar.gpd")), MSGS
assert not w.is_asm() and w.size_table.rowCount() == 1 and w.size_table.item(0, 0).text() == "bar", (w.size_table.rowCount(), w.size_table.item(0, 0).text())
auto = sm.auto_h(w.geom)
assert w.size_table.item(0, 1).text() == f"auto ({auto:.4g})" and w.size_table.item(0, 2).text() == "" and w.setup["h"] == 0.0
assert "Size (mm)" in w.size_table.horizontalHeaderItem(1).text()
lo = next(f["id"] for f in w.geom["faces"] if f["normal"][0] < -0.99)
hi = next(f["id"] for f in w.geom["faces"] if f["normal"][0] > 0.99)
w.select_faces([lo]); assert w.add_support("fixed")
w.select_faces([hi]); assert w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.size_table.item(0, 1).setText("4")                                              # what typing in the cell does
assert w.setup["h"] == 4.0 and w.size_table.item(0, 1).text() == "4", (w.setup["h"], w.size_table.item(0, 1).text())
assert w.run_mesh() and "element size 4 mm" in w.mesh_lbl.text(), w.mesh_lbl.text()
n_el = len(w.mesh_q["tets"])
assert w.size_table.item(0, 2).text() == f"{n_el:,}" and n_el > 100, (w.size_table.item(0, 2).text(), n_el)
w.size_table.item(0, 1).setText("abc")                                            # not a number: said, undone, the mesh is kept
assert "not a number" in w.status_lbl.text() and w.size_table.item(0, 1).text() == "4" and w.setup["h"] == 4.0 and w.mesh_q is not None
w.size_table.item(0, 1).setText("-2")
assert "negative" in w.status_lbl.text() and w.setup["h"] == 4.0
w.size_table.item(0, 1).setText("5")                                              # a new size: the mesh is gone, its element count is cleared
assert w.mesh_q is None and w.size_table.item(0, 2).text() == "" and w.setup["h"] == 5.0
assert w.run_solve() and abs(w.result["umax"] - 1000 * 100 / (100 * 200000)) / 0.005 < 0.03
assert w.size_table.item(0, 2).text() == f"{w.result['n_elements']:,}" and "element size 5 mm" in w.mesh_lbl.text()
w.size_table.item(0, 1).setText("")                                               # blank = automatic again
assert w.setup["h"] == 0.0 and w.size_table.item(0, 1).text().startswith("auto (")
w.size_table.item(0, 1).setText("auto (3)")                                       # the automatic text itself also means automatic
assert w.setup["h"] == 0.0
w.set_size("6"); w.inputs_changed()                                               # what scripts and the old tests do
assert w.setup["h"] == 6.0
assert solid_study.SolidStudy(w).params()[[p["id"] for p in solid_study.SolidStudy(w).params()].index("sf.h")]["now"] == "6"
solid_study.SolidStudy(w).set_live("sf.h", "7.5")                                 # the study's element size lands in the table
assert w.setup["h"] == 7.5 and w.size_table.item(0, 1).text() in ("7.5",), w.size_table.item(0, 1).text()
w.fill_part_sizes()
assert w.size_table.item(0, 1).text() == "7.5"
w.save()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w2.setup["h"] == 7.5 and w2.size_table.rowCount() == 1 and w2.size_table.item(0, 1).text() == "7.5"
print("single part ok")

# ---- an assembly: steel base under an aluminium cap
ad = os.path.join(T, "asm")
os.makedirs(ad)
make_part(os.path.join(ad, "base.gpd"), 20.0, 30.0)
make_part(os.path.join(ad, "cap.gpd"), 20.0, 20.0, ALU)
asm = make_asm(ad, [("base.gpd", (0, 0, 0)), ("cap.gpd", (0, 0, 30))], "stack.gpa")
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "stack_study")) and w.import_file(asm), MSGS
assert w.is_asm() and w.size_table.rowCount() == 2
names = [x["name"] for x in w.geom["bodies"]]
assert [w.size_table.item(i, 0).text() for i in range(2)] == names
assert all(w.size_table.item(i, 1).text().startswith("auto (") for i in range(2)) and w.setup["h"] == 0.0 and w.setup["body_h"] == {}
g_ = w.geom
bottom_ = next(f["id"] for f in g_["faces"] if not f["interface"] and f["normal"][2] < -0.99)
topf_ = next(f["id"] for f in g_["faces"] if not f["interface"] and f["normal"][2] > 0.99)
w.select_faces([bottom_]); assert w.add_support("fixed")
w.select_faces([topf_]); assert w.add_load("force", {"f": [0.0, 0.0, -10000.0]})
base_i = names.index(next(n for n in names if "base" in n.lower()))
cap_i = 1 - base_i
w.size_table.item(base_i, 1).setText("6")
w.size_table.item(cap_i, 1).setText("2.5")
assert w.setup["body_h"] == {names[base_i]: 6.0, names[cap_i]: 2.5} and w.setup["h"] == 0.0, w.setup["body_h"]
assert [w.size_table.item(i, 1).text() for i in (base_i, cap_i)] == ["6", "2.5"]
assert w.run_mesh() and "element sizes 2.5 to 6 mm" in w.mesh_lbl.text(), w.mesh_lbl.text()
q = w.mesh_q
shared = set(np.unique(q["groups"][0]["conn"][:, :4])) & set(np.unique(q["groups"][1]["conn"][:, :4]))
assert len(shared) > 30, len(shared)                                              # the parts share the nodes of their joint
cnt = [int(w.size_table.item(i, 2).text().replace(",", "")) for i in range(2)]
assert cnt == [n_of(q, base_i), n_of(q, cap_i)] if base_i == 0 else cnt == [n_of(q, 0), n_of(q, 1)], cnt
assert cnt[cap_i] > cnt[base_i] * 0.7, cnt                                         # the cap is smaller (8000 against 12000 mm3) but meshed 2.4 times finer
assert w.run_solve() and w.result is not None, w.status_lbl.text()
assert w.result["equilibrium"] < 1e-6 and [p["h"] for p in w.result["part_sizes"]] == [6.0 if i == base_i else 2.5 for i in range(2)]
txt = w.res_lbl.text()
assert f"Element size, {names[base_i]}" in txt and f"Element size, {names[cap_i]}" in txt, txt[-600:]
assert w.mesh_lbl.text().startswith(f"{w.result['n_elements']:,} tetrahedra")

# a bad number in one row: said, undone; clearing a row makes the part automatic again; typing marks the mesh as old
w.size_table.item(cap_i, 1).setText("oops")
assert "not a number" in w.status_lbl.text() and names[cap_i] in w.status_lbl.text() and w.size_table.item(cap_i, 1).text() == "2.5"
w.size_table.item(cap_i, 1).setText("")
assert w.setup["body_h"] == {names[base_i]: 6.0} and w.size_table.item(cap_i, 1).text().startswith("auto (") and w.result is None
w.size_table.item(cap_i, 1).setText("2.5")

# save, reopen: the sizes are kept and shown
w.save()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w2.setup["body_h"] == {names[base_i]: 6.0, names[cap_i]: 2.5} and [w2.size_table.item(i, 1).text() for i in (base_i, cap_i)] == ["6", "2.5"]
assert w2.run_mesh() and "element sizes 2.5 to 6 mm" in w2.mesh_lbl.text(), w2.mesh_lbl.text()
print("assembly sizes ok")

# a project saved before the table: ONE size for every part - each part gets it, the meshes are the same as before
sp_ = sp.state_path(w.path)
st_ = json.load(open(sp_))
st_["setup"]["h"] = 7.0
st_["setup"].pop("body_h", None)
json.dump(st_, open(sp_, "w"))
wo = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert wo.setup["h"] == 0.0 and wo.setup["body_h"] == {names[0]: 7.0, names[1]: 7.0} and [wo.size_table.item(i, 1).text() for i in range(2)] == ["7", "7"], wo.setup
assert wo.run_mesh()
ref = sm.get_mesh(wo.geom, 7.0, {}, lambda: False, lambda t: None, None)
assert len(wo.mesh_q["tets"]) == len(ref["tets"]), (len(wo.mesh_q["tets"]), len(ref["tets"]))
assert smesh.resolve(wo.geom, wo.setup, 7.0) is None, "every part has the old size: the plain mesh and the plain key as before"
print("old project ok")

# local sizes next to sizes of the parts (Advanced): a face is compared with the size of its own part
w.cb_adv.setChecked(True)
w.size_table.item(base_i, 1).setText("8"); w.size_table.item(cap_i, 1).setText("3")
w.select_faces([bottom_]); w.e_face_h.setText("5"); w.b_face_size.click()          # the base's face: 5 is under the base's 8 (above the cap's 3)
assert len(w.setup["mesh"]["face_sizes"]) == 1, w.status_lbl.text()
w.select_faces([bottom_]); w.e_face_h.setText("9"); w.b_face_size.click()
assert w.setup["mesh"]["face_sizes"][0]["h"] == 5.0 and "smaller" in w.status_lbl.text()
w.select_faces([topf_]); w.e_face_h.setText("4"); w.b_face_size.click()           # the cap's face: 4 is above the cap's 3
assert len(w.setup["mesh"]["face_sizes"]) == 1 and "smaller" in w.status_lbl.text()
w.select_faces([topf_]); w.e_face_h.setText("2"); w.b_face_size.click()
assert len(w.setup["mesh"]["face_sizes"]) == 2
w.size_table.item(cap_i, 1).setText("1.8")                                        # the cap gets finer than the 2 mm on its face: said, and nothing is meshed
assert "smaller" in w.status_lbl.text() and abs(w.setup["body_h"][names[cap_i]] - 1.8) < 1e-9
assert not w.run_mesh() and "smaller" in w.status_lbl.text() and w.mesh_q is None
w.size_table.item(cap_i, 1).setText("3")
assert w.run_mesh() and w.mesh_q is not None, w.status_lbl.text()
w.cb_adv.setChecked(False)
print("local sizes ok")

# a thin part with a coarse size is marked
make_part(os.path.join(ad, "sheet.gpd"), 20.0, 2.0)
asm2 = make_asm(ad, [("base.gpd", (0, 0, 0)), ("sheet.gpd", (0, 0, 30))], "sheeted.gpa")
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "sheet_study")) and w.import_file(asm2), MSGS
nm = [x["name"] for x in w.geom["bodies"]]
si = nm.index(next(n for n in nm if "sheet" in n.lower()))
bi = 1 - si
w.size_table.item(si, 1).setText("6")
it = w.size_table.item(si, 1)
assert "thick" in it.toolTip() and it.foreground().color().red() > 150 and it.foreground().color().blue() < 50, (it.toolTip(), it.foreground().color().getRgb())
assert w.size_table.item(bi, 1).toolTip() == ""
w.size_table.item(si, 1).setText("1")
assert w.size_table.item(si, 1).toolTip() == ""
print("thin part ok")

# the units: the table shows the program's length unit
import unitctl, units
unitctl.set_units("in-lb-psi" if units.valid("in-lb-psi") else next(n for n in units.SYSTEMS if units.get(n)["L"] == "in"), persist=False)
assert solid_tab.UD()["L"] == "in"
w.units_changed()
assert "(in" in w.h_label.text() and "in" in w.size_table.horizontalHeaderItem(1).text()
assert abs(float(w.size_table.item(si, 1).text()) - solid_tab.l_out(1.0)) < 1e-6, w.size_table.item(si, 1).text()
w.size_table.item(si, 1).setText("0.1")                                            # 0.1 in = 2.54 mm
assert abs(w.setup["body_h"][nm[si]] - 2.54) < 1e-9, w.setup["body_h"]
unitctl.set_units("mm" if units.valid("mm") else units.DEFAULT, persist=False)
print("PASS test_solid_part_sizes")
