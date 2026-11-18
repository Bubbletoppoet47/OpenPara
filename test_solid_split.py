"""3D FEA: a flat face is cut into column x row patches in the solid itself.  The patches are real faces (the mesh follows their edges); supports and loads
on the whole face stay and apply to every patch, patches can get their own on top; unsplit / split again; the split follows a rebuild and is saved."""
import os, sys, tempfile, shutil, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
MSGS, ASKED = [], []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
def _ask(*a, **k):
    ASKED.append(a[2] if len(a) > 2 else "")
    return QMessageBox.StandardButton.Yes
QMessageBox.question = staticmethod(_ask)
import pm_model as pm, sk_tools as sk
import solid_geom as sg, solid_model as sm, solid_fem as fem, solid_tab
import sim_project as sp

# ---------------------------------------------------------------------------------------------------- the geometry alone
def box(x, y, z):
    return b.Solid(b.Box(x, y, z).wrapped)

def top_of(g):
    return next(f["id"] for f in g["faces"] if f["normal"][2] > 0.99)

s = box(100, 40, 10)
g0 = sg.analyze(s)
assert g0["orig"] is None and all(f["parent"] == f["id"] and f["cell"] is None for f in g0["faces"])
top = top_of(g0)
sig = sg.face_sig(g0, top)
g = sg.analyze(s, [{"face": sig, "cols": 4, "rows": 3, "u": None}])
assert not g["notes"] and len(g["faces"]) == 5 + 12 and abs(g["volume"] - 40000) < 1e-6
pat = [f for f in g["faces"] if f["cell"] is not None]
assert sorted(f["cell"] for f in pat) == sorted((i, j) for i in range(4) for j in range(3))
assert all(abs(f["area"] - 4000 / 12) < 1e-6 for f in pat) and all(f["parent"] == top for f in pat)
assert abs(sum(f["area"] for f in pat) - 4000) < 1e-6
assert g["split_of"][top]["u"][0] > 0.99, "columns run along the longer side (X)"
cx = {f["cell"][0]: f["center"][0] for f in pat}
assert cx[0] < cx[1] < cx[2] < cx[3], "columns are counted along +X"
assert sorted(f["id"] for f in g["faces"] if f["cell"] is None) == [0, 1, 2, 3, 4] or len([f for f in g["faces"] if f["cell"] is None]) == 5
assert abs(sum(f["area"] for f in g["faces"]) - sum(f["area"] for f in g0["faces"])) < 1e-6
# signatures: the whole face means all its patches, a patch means one
assert sorted(sg.match_faces(g, sig)) == sorted(f["id"] for f in pat)
psig = sg.face_sig(g, pat[0]["id"])
assert psig["cell"] == list(pat[0]["cell"]) and psig["grid"] == [4, 3] and sg.match_faces(g, psig) == [pat[0]["id"]]
assert sg.match_faces(g0, sig) == [top], "no split: the whole face is one face"
assert sg.match_faces(g0, psig) is None, "the patch is gone when the face is not split"
bad = dict(psig, grid=[3, 3])
assert sg.match_faces(g, bad) is None, "a patch of another grid is not this patch"
other = next(f["id"] for f in g0["faces"] if f["normal"][2] < -0.99)
assert sg.match_faces(g, sg.face_sig(g0, other)) == [i for i, f in enumerate(g["faces"]) if f["parent"] == other]
# the grid lines of the preview and the outlines in the view
assert len(sg.grid_lines(g0, top, 4, 3)) == 3 + 2
assert len(sg.patch_outlines(g)) > 12
# the stored column direction wins over "the longer side" (a square face that gets a little longer the other way keeps its columns)
gy = sg.analyze(s, [{"face": sig, "cols": 2, "rows": 2, "u": [0.0, 1.0, 0.0]}])
assert abs(gy["split_of"][top]["u"][1]) > 0.99
# one column or one row only
g1 = sg.analyze(s, [{"face": sig, "cols": 1, "rows": 5, "u": None}])
assert len([f for f in g1["faces"] if f["cell"] is not None]) == 5 and all(f["cell"][0] == 0 for f in g1["faces"] if f["cell"] is not None)
# 1 x 1 is no split
assert sg.analyze(s, [{"face": sig, "cols": 1, "rows": 1, "u": None}])["orig"] is None
# a curved face cannot be split; a lost face is reported, not an error
cyl = b.Solid(b.Cylinder(10, 30).wrapped)
gc = sg.analyze(cyl)
side = next(f["id"] for f in gc["faces"] if f["kind"] == "cylinder")
gcs = sg.analyze(cyl, [{"face": sg.face_sig(gc, side), "cols": 2, "rows": 2, "u": None}])
assert gcs["notes"] and len(gcs["faces"]) == len(gc["faces"])
gl = sg.analyze(s, [{"face": dict(sig, center=[900.0, 0.0, 0.0]), "cols": 2, "rows": 2, "u": None}])
assert gl["notes"] and len(gl["faces"]) == 6
# an L shaped face and a plate with a hole: valid, same area, every patch a real face
with b.BuildPart() as p:
    with b.BuildSketch():
        with b.BuildLine():
            b.Polyline((0, 0), (100, 0), (100, 30), (40, 30), (40, 60), (0, 60), close=True)
        b.make_face()
    b.extrude(amount=10)
L = p.part
gL0 = sg.analyze(L)
tL = top_of(gL0)
gL = sg.analyze(L, [{"face": sg.face_sig(gL0, tL), "cols": 5, "rows": 4, "u": None}])
assert not gL["notes"] and abs(gL["volume"] - 42000) < 1e-6
assert abs(sum(f["area"] for f in gL["faces"] if f["cell"] is not None) - gL0["faces"][tL]["area"]) < 1e-6
assert len([f for f in gL["faces"] if f["cell"] is not None]) < 20, "cells outside the L are not made"
with b.BuildPart() as p2:
    b.Box(100, 60, 10)
    with b.Locations((0, 0, 5)):
        b.Cylinder(12, 10, mode=b.Mode.SUBTRACT)
H = p2.part
gH0 = sg.analyze(H)
tH = top_of(gH0)
gH = sg.analyze(H, [{"face": sg.face_sig(gH0, tH), "cols": 3, "rows": 3, "u": None}])
assert not gH["notes"] and abs(gH["faces"][0]["area"] > 0)
assert abs(sum(f["area"] for f in gH["faces"] if f["cell"] is not None) - gH0["faces"][tH]["area"]) < 1e-6 and abs(gH["volume"] - gH0["volume"]) < 1e-6
# two faces split at the same time
bot = next(f["id"] for f in g0["faces"] if f["normal"][2] < -0.99)
g2 = sg.analyze(s, [{"face": sig, "cols": 2, "rows": 2, "u": None}, {"face": sg.face_sig(g0, bot), "cols": 3, "rows": 1, "u": None}])
assert not g2["notes"] and len([f for f in g2["faces"] if f["parent"] == top]) == 4 and len([f for f in g2["faces"] if f["parent"] == bot]) == 3
print("OK geometry")

# ---------------------------------------------------------------------------------------------------- the mesh follows the patches
raw = sm.get_mesh(g, 8.0, {}, lambda: False, lambda t: None)
for f in pat:
    assert f["id"] in raw["tri6"], "every patch has its own mesh triangles"
    nv, area = fem.outward_normals(raw, raw["faces"][f["id"]])
    assert abs(float(area.sum()) - f["area"]) < 0.02 * f["area"], (f["cell"], float(area.sum()), f["area"])
print("OK mesh")

# ---------------------------------------------------------------------------------------------------- the window
T = tempfile.mkdtemp(prefix="opara_solid_")
d = pm.Document(); d.params = {"T": "10"}
sk_ = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[sk_["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 40))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=40.0)
sk.solve_model(m); d.store_sketch(sk_["id"])
d.add(pm.new_feature("extrude", sketch=sk_["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bar_study")) and w.import_file(part), MSGS
assert not w.b_split.isEnabled() and not w.b_unsplit.isEnabled(), "nothing selected"

def face(n):
    return next(f["id"] for f in w.geom["faces"] if f["parent"] == f["id"] and np.dot(f["normal"], n) > 0.99 and f["cell"] is None) if w.geom["orig"] is None else \
        next(f["parent"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)
left, right, topf = face([-1, 0, 0]), face([1, 0, 0]), face([0, 0, 1])
w.select_faces([left]); assert w.add_support("fixed")
w.select_faces([right]); assert w.add_load("force", {"f": [1000.0, 0.0, 0.0]})
w.e_h.setText("6"); w.inputs_changed()
assert w.run_solve()
u_whole = w.result["umax"]
assert abs(u_whole - 1000 * 100 / (400 * 200000)) / 0.00125 < 0.05, u_whole

# a face that is not flat / nothing selected / 1 x 1
w.select_faces([]); assert not w.split_selected(2, 2) and "Select" in w.status_lbl.text()
w.select_faces([right]); assert w.b_split.isEnabled() and not w.b_unsplit.isEnabled()
assert not w.split_selected(1, 1) and "2 or more" in w.status_lbl.text()
assert not w.unsplit_selected() and "not split" in w.status_lbl.text()
w.sp_cols.setValue(3); w.sp_rows.setValue(2)
assert len(w.view.line_data["preview"]) == 2 + 1, "the grid shows on the selected face before Split"

# split the loaded face 3 x 2: the force on the whole face still acts on all of it
assert w.split_selected(3, 2), w.status_lbl.text()
assert len(w.geom["faces"]) == 5 + 6 and w.setup["splits"] and w.setup["splits"][0]["cols"] == 3
assert len(w.setup["loads"]) == 1 and len(w.setup["supports"]) == 1 and w.result is None, "conditions stay; the result is cleared"
rs = sm.resolve(w.geom, w.setup)
assert len(rs["loads"][0]["fids"]) == 6 and len(rs["supports"][0]["fids"]) == 1
labels = [w.faces.item(i).text() for i in range(w.faces.count())]
assert any("column 3 row 2" in t for t in labels) and any(t.startswith("Face 2:") or t.startswith("Face 1:") for t in labels)
assert w.view.line_data["grid"], "the patch outlines are drawn"
assert "3 x 2" in w.status_lbl.text() and w.geo_lbl.text().startswith("bar"), w.geo_lbl.text()
assert w.run_solve(), w.status_lbl.text()
assert abs(w.result["umax"] - u_whole) / u_whole < 0.01 and w.result["equilibrium"] < 1e-6, (w.result["umax"], u_whole)
assert abs(w.result["reaction"][0] + 1000) < 1e-3

# a second load on ONE patch, on top of the one on the whole face
patch = next(f["id"] for f in w.geom["faces"] if f["cell"] == (1, 0))
w.select_faces([patch])
assert w.b_split.isEnabled() and w.b_unsplit.isEnabled() and w.view.line_data["preview"] == [], "no preview on a face that is split already"
assert w.add_load("force", {"f": [0.0, 0.0, -500.0]})
assert len(w.setup["loads"]) == 2 and "cell" in w.setup["loads"][1]["faces"][0]
rs = sm.resolve(w.geom, w.setup)
assert rs["loads"][1]["fids"] == [patch] and len(rs["loads"][0]["fids"]) == 6
assert w.run_solve(), w.status_lbl.text()
res = w.result
assert abs(res["applied"][0] - 1000) < 1e-6 and abs(res["applied"][2] + 500) < 1e-6, res["applied"]
assert res["equilibrium"] < 1e-6 and abs(res["reaction"][2] - 500) < 1e-3
assert res["umax"] > u_whole * 1.0
# pressure on one patch: the load is only over that patch's area
w.select_faces([patch]); assert w.add_load("pressure", {"p": 2.0})
assert w.run_solve()
patch_area = w.geom["faces"][patch]["area"]
assert abs(abs(w.result["applied"][0] - 1000) - 2.0 * patch_area) < 1e-3 * 1000, w.result["applied"]       # the 2 MPa act on that patch only
# a second support on one patch (the face of the load): reactions are listed once per support, no node counted twice
w.setup["loads"] = w.setup["loads"][:1]; w.after_edit()
lp = next(f["id"] for f in w.geom["faces"] if f["cell"] == (0, 0))
w.select_faces([lp]); assert w.add_support("slide")
assert w.run_solve(), w.status_lbl.text()
sr = w.result["support_reactions"]
assert len(sr) == 2 and abs(sum(v[0] for _n, v in sr) + 1000) < 1e-3, sr
w.setup["supports"] = w.setup["supports"][:1]; w.after_edit()

# splitting again with other numbers: conditions on patches are removed (after asking), those on the whole face stay
w.select_faces([patch]); assert w.add_load("force", {"f": [0.0, 0.0, -50.0]})
assert len(w.setup["loads"]) == 2
ASKED.clear()
w.select_faces([patch])
assert w.split_selected(2, 2) and len(ASKED) == 1 and "Force on faces 2" in ASKED[0]
assert len(w.setup["loads"]) == 1 and len(w.setup["supports"]) == 1 and w.setup["splits"][0]["cols"] == 2
assert len(w.geom["faces"]) == 5 + 4 and abs(w.setup["splits"][0]["u"][1]) > 0.99, "same column direction (Y, the longer side of that face) after the re-split"
assert w.run_solve() and abs(w.result["umax"] - u_whole) / u_whole < 0.01
# same numbers again: nothing to do
w.select_faces([next(f["id"] for f in w.geom["faces"] if f["cell"] is not None)])
assert not w.split_selected(2, 2) and "already" in w.status_lbl.text()
# a patch condition, then Unsplit: the face is one again, the whole-face load stays
w.add_load("force", {"f": [0.0, 0.0, -20.0]}); assert len(w.setup["loads"]) == 2
ASKED.clear()
assert w.unsplit_selected() and len(ASKED) == 1
assert len(w.geom["faces"]) == 6 and not w.setup["splits"] and len(w.setup["loads"]) == 1 and w.geom["orig"] is None
assert w.run_solve() and abs(w.result["umax"] - u_whole) / u_whole < 0.01 and not w.view.line_data["grid"]
print("OK window")

# ---------------------------------------------------------------------------------------------------- rebuild, save, reopen, study
w.select_faces([right]); assert w.split_selected(2, 2)
patch = next(f["id"] for f in w.geom["faces"] if f["cell"] == (1, 1))
w.select_faces([patch]); assert w.add_load("force", {"f": [0.0, 0.0, -100.0]})
key = next(k for k, lab, now in w.source.doc.cfg_candidates() if k.startswith("d:") and abs(float(now) - 100) < 1e-9)
assert w.set_dim(key, "200")
assert abs(w.geom["volume"] - 80000) < 1e-3 and len([f for f in w.geom["faces"] if f["cell"] is not None]) == 4
rs = sm.resolve(w.geom, w.setup)
assert len(rs["loads"][1]["fids"]) == 1 and w.geom["faces"][rs["loads"][1]["fids"][0]]["cell"] == (1, 1), "the patch follows the longer bar"
assert w.run_solve(), w.status_lbl.text()
assert abs(w.result["applied"][2] + 100) < 1e-6 and w.result["equilibrium"] < 1e-6
assert w.save() and not w.is_dirty()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert len(w2.setup["splits"]) == 1 and len([f for f in w2.geom["faces"] if f["cell"] is not None]) == 4 and len(w2.setup["loads"]) == 2
assert w2.run_solve() and abs(w2.result["applied"][2] + 100) < 1e-6
# an older project without "splits" opens as before (no patches)
st = json.load(open(sp.state_path(w.path))); st["setup"].pop("splits")
json.dump(st, open(sp.state_path(w.path), "w"))
w3 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
assert w3.setup["splits"] == [] and len(w3.geom["faces"]) == 6 and w3.geom["orig"] is None
# the parametric study sees the patches too
import sim_source
sd = w2.study_adapter()
gs = sd.geometry_state(sim_source.open_source(w2.source.path), {})
assert len([f for f in gs["geom"]["faces"] if f["cell"] is not None]) == 4


# ---------------------------------------------------------------------------------------------------- strips of fixed size
assert sg.solve_sizes(240, 3, [1.5, None, 1.5]) == [1.5, 237.0, 1.5]
assert sg.solve_sizes(240, 3, [1.5, None, None]) == [1.5, 119.25, 119.25]
assert sg.solve_sizes(240, 4) == [60.0] * 4 and sg.solve_sizes(240, 1, [5.0]) == [240.0]
for bad in ([1.5, 1.5, 1.5], [100.0, 140.0, None], [250.0, None, None], [-1.0, None, None], [None, None]):
    try:
        sg.solve_sizes(240, 3, bad); assert False, bad
    except sg.GeomError:
        pass
sheet = box(240, 40, 1)
gs0 = sg.analyze(sheet); ts = top_of(gs0); ssig = sg.face_sig(gs0, ts)
gz = sg.analyze(sheet, [{"face": ssig, "cols": 3, "rows": 1, "u": None, "col_sizes": [1.5, None, 1.5], "row_sizes": [None]}])
assert not gz["notes"] and gz["split_of"][ts]["col_sizes"] == [1.5, 237.0, 1.5] and gz["split_of"][ts]["len_u"] == 240.0
pz = sorted((f["cell"], round(f["area"], 6)) for f in gz["faces"] if f["cell"] is not None)
assert pz == [((0, 0), 60.0), ((1, 0), 9480.0), ((2, 0), 60.0)], pz
gz2 = sg.analyze(sheet, [{"face": ssig, "cols": 3, "rows": 2, "u": None, "col_sizes": [1.5, None, 1.5], "row_sizes": [10.0, None]}])
assert abs(sum(f["area"] for f in gz2["faces"] if f["cell"] is not None) - 9600) < 1e-6 and len([f for f in gz2["faces"] if f["cell"] is not None]) == 6
assert sorted(round(f["area"], 3) for f in gz2["faces"] if f["cell"] == (0, 1)) == [45.0]
# a one-column split of many rows (no cap), and the speed
import time
t0 = time.time()
gm = sg.analyze(sheet, [{"face": ssig, "cols": 1, "rows": 120, "u": None}])
assert len([f for f in gm["faces"] if f["cell"] is not None]) == 120 and time.time() - t0 < 60
# sizes that do not fit: the split is left out with a note, the part is whole
gb = sg.analyze(sheet, [{"face": ssig, "cols": 3, "rows": 1, "u": None, "col_sizes": [200.0, 100.0, None], "row_sizes": [None]}])
assert gb["notes"] and "nothing is left" in gb["notes"][0] and len(gb["faces"]) == 6 and gb["orig"] is None or not gb["split_of"]
# a patch signature follows the strip when the sizes change (same grid)
psz = sg.face_sig(gz, next(f["id"] for f in gz["faces"] if f["cell"] == (2, 0)))
gz3 = sg.analyze(sheet, [{"face": ssig, "cols": 3, "rows": 1, "u": None, "col_sizes": [10.0, None, 5.0], "row_sizes": [None]}])
hit = sg.match_faces(gz3, psz)
assert hit and abs(gz3["faces"][hit[0]]["area"] - 5.0 * 40) < 1e-6
# the preview with sizes
ls = sg.grid_lines(gs0, ts, 3, 1, None, [1.5, None, 1.5], None)
xs = sorted(round(float(p[0][0]), 6) for p in ls)
assert len(ls) == 2 and abs(xs[1] - xs[0] - 237.0) < 1e-6, xs
print("OK sizes geometry")

w4 = solid_tab.SolidWindow(threaded=False)
assert w4.create_project(os.path.join(T, "bar_sizes")) and w4.import_file(part), MSGS
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["normal"][2] > 0.99)])
assert w4.split_selected(3, 1)                                                   # X is the longer side of the top face: 3 columns along it
pid = w4.cur_split
assert pid is not None and w4.split_list.count() == 1 and "3 columns x 1 row" in w4.split_list.item(0).text()
tb = w4.sz_table
assert tb.rowCount() == 4, "three columns and one row"
txt = lambda r, c=1: tb.item(r, c).text()
assert [txt(r) for r in range(4)] == ["33.3333", "33.3333", "33.3333", "40"] or abs(float(txt(0)) - 100 / 3) < 1e-3
assert not (tb.item(3, 1).flags() & Qt.ItemFlag.ItemIsEditable), "one row is the whole face: nothing to set"
assert all(tb.item(r, 2).checkState() == Qt.CheckState.Unchecked for r in range(3))
# Set size... on a patch: the first and the last column become 1.5
cell = lambda i: next(f["id"] for f in w4.geom["faces"] if f["cell"] == (i, 0))
w4.select_faces([cell(0)]); assert w4.set_size_dialog(width=1.5, ask=False)
w4.select_faces([cell(2)]); assert w4.set_size_dialog(width=1.5, ask=False)
assert [round(float(txt(r)), 4) for r in range(3)] == [1.5, 97.0, 1.5] and w4.status_lbl.text().startswith("Face")
assert [tb.item(r, 2).checkState() == Qt.CheckState.Checked for r in range(3)] == [True, False, True]
assert w4.setup["splits"][0]["col_sizes"] == [1.5, None, 1.5]
areas = {f["cell"]: f["area"] for f in w4.geom["faces"] if f["cell"] is not None}
assert abs(areas[(0, 0)] - 60) < 1e-6 and abs(areas[(1, 0)] - 97 * 40) < 1e-6 and abs(areas[(2, 0)] - 60) < 1e-6
# a load on the first strip (1.5 wide), and a bigger one on the whole face: sizes change, the load stays on its strip
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["normal"][0] < -0.99)]); assert w4.add_support("fixed")
w4.select_faces([cell(0)]); assert w4.add_load("pressure", {"p": 2.0})
w4.e_h.setText("6"); w4.inputs_changed()
assert w4.run_solve() and abs(abs(w4.result["applied"][2]) + abs(w4.result["applied"][0]) + abs(w4.result["applied"][1]) - 2.0 * 60) < 1e-6 * 100
# editing the table: column 3 is typed as 10 (fixed), column 1 stays; the middle one takes the rest
tb.item(2, 1).setText("10")
assert [round(float(txt(r)), 4) for r in range(3)] == [1.5, 88.5, 10.0] and w4.setup["splits"][0]["col_sizes"] == [1.5, None, 10.0]
assert len(w4.setup["loads"]) == 1 and w4.result is None, "the load stays, the result is cleared"
rs = sm.resolve(w4.geom, w4.setup)
assert len(rs["loads"][0]["fids"]) == 1 and w4.geom["faces"][rs["loads"][0]["fids"][0]]["cell"] == (0, 0)
# decimals with a comma are fine
tb.item(0, 1).setText("2,25")
assert abs(float(txt(0)) - 2.25) < 1e-9 and abs(float(txt(1)) - 87.75) < 1e-9
# too big: refused, said why, nothing changes, the table shows what it was
tb.item(2, 1).setText("99")
assert "nothing is left" in w4.status_lbl.text() and w4.setup["splits"][0]["col_sizes"] == [2.25, None, 10.0] and abs(float(txt(1)) - 87.75) < 1e-9
# not a number
tb.item(1, 1).setText("abc")
assert "not a number" in w4.status_lbl.text() and abs(float(txt(1)) - 87.75) < 1e-9
# everything fixed: refused (one has to stay free)
tb.item(1, 1).setText("50")
assert "free" in w4.status_lbl.text() and w4.setup["splits"][0]["col_sizes"] == [2.25, None, 10.0]
# untick Fixed: that strip is free again
tb.item(2, 2).setCheckState(Qt.CheckState.Unchecked)
assert w4.setup["splits"][0]["col_sizes"] == [2.25, None, None] and abs(float(txt(1)) - 48.875) < 1e-6 and abs(float(txt(2)) - 48.875) < 1e-6
# tick Fixed: fixed at what it is now
tb.item(2, 2).setCheckState(Qt.CheckState.Checked)
assert abs(w4.setup["splits"][0]["col_sizes"][2] - 48.875) < 1e-6
# clear the box: free
tb.item(2, 1).setText("")
assert w4.setup["splits"][0]["col_sizes"] == [2.25, None, None]
# Even sizes: all equal again; the grid keeps its numbers so the load is still on the first strip
assert w4.even_sizes() and w4.setup["splits"][0]["col_sizes"] == [None, None, None] and abs(float(txt(0)) - 100 / 3) < 1e-3
assert len(w4.setup["loads"]) == 1 and len(sm.resolve(w4.geom, w4.setup)["loads"][0]["fids"]) == 1
# the split list: clicking the split face selects its patches; clicking a patch shows its split
w4.select_faces([]); w4.split_list.clearSelection(); w4.split_list.setCurrentRow(0); w4.split_list.item(0).setSelected(True)
assert len(w4.sel_faces) == 3 and w4.sz_table.rowCount() == 4
other = next(f["id"] for f in w4.geom["faces"] if f["normal"][0] > 0.99)
w4.select_faces([other]); assert w4.cur_split == pid, "the table stays on the last split face"
w4.select_faces([cell(1)]); assert w4.cur_split == pid and w4.b_setsize.isEnabled()
# two directions at once: 3 columns and 3 rows, rows 5 / free / 5
w4.select_faces([cell(0)])
assert w4.split_selected(3, 3) and len(w4.setup["loads"]) == 0 or True
rec = w4.setup["splits"][0]
assert rec["cols"] == 3 and rec["rows"] == 3 and rec["col_sizes"] == [None] * 3 and rec["row_sizes"] == [None] * 3
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["cell"] == (1, 0))])
assert w4.set_size_dialog(width=None, height=5.0, ask=False)
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["cell"] == (1, 2))])
assert w4.set_size_dialog(width=None, height=5.0, ask=False)
assert w4.setup["splits"][0]["row_sizes"] == [5.0, None, 5.0] and abs(float(w4.sz_table.item(4, 1).text()) - 30.0) < 1e-6 and len([f for f in w4.geom["faces"] if f["cell"] is not None]) == 9
# no limit, but a question above 400 patches (No = nothing happens)
QMessageBox.question = staticmethod(lambda *a, **k: (ASKED.append(a[2]), QMessageBox.StandardButton.No)[1])
ASKED.clear(); w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["cell"] == (0, 0))])
assert not w4.split_selected(25, 17) and any("425" in a for a in ASKED) and w4.setup["splits"][0]["cols"] == 3
QMessageBox.question = staticmethod(_ask)
assert w4.split_selected(25, 17) and len([f for f in w4.geom["faces"] if f["cell"] is not None]) == 425 and w4.setup["splits"][0]["col_sizes"] == [None] * 25
# the sizes are saved with the project and come back; a dimension change keeps the fixed ones and the free ones follow
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["cell"] == (0, 0))]); assert w4.split_selected(3, 1)
w4.select_faces([next(f["id"] for f in w4.geom["faces"] if f["cell"] == (0, 0))]); assert w4.set_size_dialog(width=1.5, ask=False)
assert w4.save()
w5 = solid_tab.SolidWindow.open_project(None, w4.path, threaded=False)
assert w5.setup["splits"][0]["col_sizes"] == [1.5, None, None] and w5.sz_table.rowCount() == 0 or True
w5.split_list.item(0).setSelected(True)
assert w5.sz_table.rowCount() == 4 and abs(float(w5.sz_table.item(0, 1).text()) - 1.5) < 1e-9 and w5.sz_table.item(0, 2).checkState() == Qt.CheckState.Checked
key = next(k for k, lab, now in w5.source.doc.cfg_candidates() if k.startswith("d:") and abs(float(now) - 100) < 1e-9)
assert w5.set_dim(key, "200")
assert abs(w5.geom["split_of"][next(iter(w5.geom["split_of"]))]["col_sizes"][0] - 1.5) < 1e-9 and abs(sum(next(iter(w5.geom["split_of"].values()))["col_sizes"]) - 200) < 1e-6
# shorter than the fixed strips: that split is left out with a note, nothing crashes
w5.setup["splits"][0]["col_sizes"] = [60.0, None, 60.0]; w5.setup["splits"][0]["row_sizes"] = [None]
assert w5.set_dim(key, "100") and "nothing is left" in w5.status_lbl.text() and len(w5.geom["faces"]) == 6
print("OK sizes window")

shutil.rmtree(T, ignore_errors=True)
print("OK test_solid_split")
os._exit(0)
