import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import pm_model as pm, sk_tools as sk, asm_model as am, gpd_app, assembly, asm_patterns, pm_app
tmp = tempfile.mkdtemp()
def make_part(name, rect, depth):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
    sk.add_rect_corner(m, rect[0], rect[1]); sk.solve_model(m); d.store_sketch(s["id"])
    d.add(pm.new_feature("extrude", sketch=s["id"], depth=str(depth))); d.rebuild()
    p = os.path.join(tmp, name); open(p, "w").write(d.to_json()); return p
pa = make_part("base.gpd", ((0, 0), (60, 40)), 10); pb = make_part("block.gpd", ((0, 0), (10, 10)), 10)
sh = gpd_app.AppShell([pa]); print("tabs", sh.tabs.count(), sh.tabs.tabText(0))
w = sh.new_assembly(); print("tabs", sh.tabs.count(), [sh.tabs.tabText(i) for i in range(sh.tabs.count())])
w.insert_files([pa, pb, pb]); A = w.asm
from PyQt6.QtCore import Qt
import refgeo, asm_refs, viewpick
# a part with its own reference plane (offset of Top by 4) and axis
d = pm.Document(); s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (10, 10)); sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild()
rp = d.add(pm.new_feature("refplane", refs=[{"k": "base", "n": "Top"}], ptype="offset", d="4", ang="45", flip=False))
d.add(pm.new_feature("refaxis", refs=[{"k": "base", "n": "Front"}, {"k": "base", "n": "Right"}], ptype="planes")); d.rebuild()
pc = os.path.join(tmp, "ref.gpd"); open(pc, "w").write(d.to_json())
sh = gpd_app.AppShell([]); w = sh.new_assembly(); w.insert_files([pa, pc]); A = w.asm
c0, c1 = A.components[:2]
print("tree top items", [w.tree.topLevelItem(0).child(i).text(0) for i in range(w.tree.topLevelItem(0).childCount())])
assert [w.tree.topLevelItem(0).child(i).text(0) for i in range(4)][:3] == ["▯  Front Plane", "▯  Top Plane", "▯  Right Plane"]
# toggle origin plane via checkbox
root = w.tree.topLevelItem(0); fp = root.child(0)
fp.setCheckState(0, Qt.CheckState.Unchecked); app.processEvents(); app.processEvents()
assert A.world_show["Front"] is False and not any(g["label"] == "Front Plane" for g in w.world_geo); print("front plane hidden")
w.tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Checked); app.processEvents(); app.processEvents()
assert A.world_show["Front"] is True and any(g["label"] == "Front Plane" for g in w.world_geo)
# mate: block's bottom face coincident with the ASSEMBLY Top plane via the small tree
mt = w.mini
def find(kind, key=None, tree=None):
    stack = [mt.tree.topLevelItem(0)]
    while stack:
        it = stack.pop(); dt = it.data(0, Qt.ItemDataRole.UserRole)
        if dt and dt[0] == kind and (key is None or dt[1] == key): return it
        stack += [it.child(i) for i in range(it.childCount())]
def faces(c):
    fs = w.solid_of(c).faces(); return min(range(len(fs)), key=lambda i: fs[i].center().Z)
def R(c, i): return {"c": c["id"], "k": "face", "r": am.face_ref(w.solid_of(c).faces()[i])}
w.asm.comp(c1["id"])["pos"] = [5.0, 5.0, 30.0]
w.mate_start(); mt.clicked(find("wplane", "Top"))
w.add_mate_ref(R(c1, faces(c1)), {"cid": c1["id"], "kind": "face", "idx": faces(c1), "label": "Face"})
print("type", w.mate_type, "err", w.mate_error, [round(x, 3) for x in w.asm.comp(c1["id"])["pos"]])
w.mate_ok(); A = w.asm; c1 = A.components[1]
print("after world mate z", round(c1["pos"][2], 4), A.status)
assert abs(c1["pos"][2]) < 1e-6 and all(v == "ok" for v in A.status.values())
# an assembly reference plane: offset 25 from the assembly Front plane, via the tool
asm_refs.start(w, "refplane"); mt = w.mini; mt.clicked(find("wplane", "Front"))
print("tool", w.rg["ptype"], w.rg["err"], w.rg["ent"]["p"] if w.rg["ent"] is not None else None)
w.rg["d"] = "25"; asm_refs.refresh(w); assert abs(w.rg["ent"]["p"][1] + 25) < 1e-6
asm_refs.ok(w); A = w.asm; print("refs", [(r["name"], r["ptype"]) for r in A.refs]); assert len(A.refs) == 1
# mate the other part's side to that plane through the tree item
w.mate_start()
mt = w.mini; mt.clicked(find("aref", A.refs[0]["id"]))
cr = A.comp(c1["id"])
def sideY(c):
    fs = w.solid_of(c).faces(); return min(range(len(fs)), key=lambda i: fs[i].center().Y)
w.add_mate_ref(R(c1, sideY(c1)), {"cid": c1["id"], "kind": "face", "idx": sideY(c1), "label": "Face"})
w.mate_ok(); A = w.asm; c1 = A.components[1]
print("y after", round(c1["pos"][1], 4), A.status)
# part reference plane under the component, picked for a mate
ci = [x for x in A.components if x["id"] == c1["id"]][0]
sub = None
for i in range(w.tree.topLevelItem(0).childCount()):
    pass
d1 = w.part_doc(c1); assert any(g["kind"] == "refplane" for g in d1.features)
e = A.entity({"c": c1["id"], "k": "plane", "r": {"id": rp["id"]}}); print("part ref plane world", np.round(e["p"], 3), np.round(e["n"], 3))
# save / reload
w.path = os.path.join(tmp, "r.gpa"); w.save(); sh2 = gpd_app.AppShell([w.path]); w2 = sh2.cur()
print("reload", len(w2.asm.refs), w2.asm.world_show, [m["refs"][0]["c"] for m in w2.asm.mates], w2.asm.status)
assert len(w2.asm.refs) == 1 and any(m["refs"][0]["c"] == "@" for m in w2.asm.mates)
# edit the reference plane to 40 and watch the mate follow
asm_refs.start(w, "refplane", edit=A.refs[0]["id"]); assert len(w.rg["refs"]) == 1; w.rg["d"] = "40"; asm_refs.refresh(w); asm_refs.ok(w)
w.solve_all(); print("after edit y", round(w.asm.components[1]["pos"][1], 3), w.asm.status)
# deleting the plane removes its mate
n = len(w.asm.mates); asm_refs.delete_ref(w, w.asm.refs[0]["id"]); print("mates", n, "->", len(w.asm.mates), "refs", len(w.asm.refs))
w.do_undo(); assert len(w.asm.refs) == 1
# world pick by ray (offscreen camera): just make sure it runs
print("world_pick", asm_refs.world_pick(w, 100, 100))
print("REF ASM OK")
# ray picking with a made-up camera ray
import viewpick as _vp; _vp.world_per_pixel = lambda pl: 0.5
import numpy as np
w.ed.ray = lambda x, y: (np.array([0.5, 0.5, 100.0]), np.array([0.0, 0.0, -1.0]))
g = asm_refs.world_pick(w, 0, 0); print("ray down", g and (g["label"], g["kind"]))
assert g is not None and g["kind"] in ("plane", "origin")
w.ed.ray = lambda x, y: (np.array([0.0, 0.0, 100.0]), np.array([0.0, 0.0, -1.0]))
g = asm_refs.world_pick(w, 0, 0); print("ray at origin", g and (g["label"], g["kind"]))
assert g["kind"] == "origin" or g["kind"] == "plane"
w.ed.ray = lambda x, y: (np.array([500.0, 500.0, 100.0]), np.array([0.0, 0.0, -1.0]))
r_ = asm_refs.world_pick(w, 0, 0); print("far ray ->", r_ and r_["label"], viewpick.world_per_pixel(w.plotter), asm_refs.scene_size(w)); assert r_ is None
print("RAY OK")
# mirror a component about the assembly Right plane (x = 0)
import asm_patterns
w.set_mode(None, quiet=True)
asm_patterns.start(w, "mirror"); c_seed = w.asm.components[1]["id"]
w.pat["data"]["seeds"] = [c_seed]; w.pat["data"]["plane"] = {"ref": {"c": "@", "k": "plane", "r": {"n": "Right"}}}
w.refresh_derived(); der = [c for c in w.asm.components if c.get("derived")]
print("mirror copies", len(der), np.round(np.array(der[0]["M"])[:3, 3], 3))
assert len(der) == 1
print("PATTERN WORLD OK")
