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
import evaluate, asm_sub
from PyQt6.QtCore import Qt
pm_ = pa; 
sh = gpd_app.AppShell([]); w = sh.new_assembly(); w.insert_files([pa, pb, pb]); A = w.asm
c0, c1, c2 = A.components[:3]
def faces_by(c, key):
    fs = w.solid_of(c).faces(); return min(range(len(fs)), key=lambda i: key(fs[i].center()))
def R(c, i): return {"c": c["id"], "k": "face", "r": am.face_ref(w.solid_of(c).faces()[i])}
def mate(w, a, ia, b, ib):
    w.mate_start(); w.add_mate_ref(R(a, ia), {"cid": a["id"], "kind": "face", "idx": ia, "label": "Face"}); w.add_mate_ref(R(b, ib), {"cid": b["id"], "kind": "face", "idx": ib, "label": "Face"}); w.mate_ok()
# sub-assembly: base 60x40x10 with two blocks stacked on top
mate(w, c0, faces_by(c0, lambda c: -c.Z), c1, faces_by(c1, lambda c: c.Z)) if False else None
top = lambda c: -c.Z
mate(w, w.asm.components[0], faces_by(w.asm.components[0], lambda c: -c.Z), w.asm.components[1], faces_by(w.asm.components[1], lambda c: c.Z))  # block top on base top? (opposed)
print("sub status", w.asm.status, [round(x, 2) for x in w.asm.components[1]["pos"]])
# a second configuration: block 2 suppressed
w.asm.cfg_add("Short"); w.asm.cfg_add_col(f"x:{w.asm.components[2]['id']}"); w.asm.cfg_set_cell("Short", f"x:{w.asm.components[2]['id']}", True)
w.asm.cfg_apply("Default")
sub = os.path.join(tmp, "sub.gpa"); w.path = sub; w.save()
vol_default = evaluate.mass_properties(w.part_doc(w.asm.components[0]).solid, 7850)["mass"]
w_sub = w
# parent
sh2 = gpd_app.AppShell([]); P = sh2.new_assembly(); P.insert_files([pa]); P.insert_files([sub]); A2 = P.asm
w = P; cs = A2.components[1]; print("sub comp", cs["name"], cs["path"])
d = P.part_doc(cs); print("is_sub", getattr(d, "is_sub", False), "leaves", d.leaf_names, "cfgs", d.cfg["names"], "vol", round(d.solid.volume, 1))
assert getattr(d, "is_sub", False) and len(d.leaf_names) == 3 and abs(d.solid.volume - (60*40*10 + 2*1000)) < 1
mass_default = d.mass_pr()["mass"]
# mate the subassembly's bottom to the parent's base top
fb = faces_by(cs, lambda c: c.Z * -1)       # lowest face of the compound
base = A2.components[0]
mate(P, base, faces_by(base, lambda c: c.Z), cs, fb)
A2 = P.asm; cs = A2.components[1]; print("parent status", A2.status, [round(x, 2) for x in cs["pos"]])
assert all(v == "ok" for v in A2.status.values())
# tree shows the parts inside
root = P.tree.topLevelItem(0); found = []
def walk(it):
    found.append(it.text(0)); [walk(it.child(i)) for i in range(it.childCount())]
walk(root); assert any("Parts inside (3)" in t for t in found); print("tree ok")
# configuration of the subassembly chosen in the parent
A2.cfg_add("NoBlock"); A2.cfg_add_col(f"c:{cs['id']}"); A2.cfg_set_cell("NoBlock", f"c:{cs['id']}", "Short")
print("choices", P.cfg_choices(f"c:{cs['id']}"))
assert "Short" in P.cfg_choices(f"c:{cs['id']}")
P.asm.cfg_apply("NoBlock"); P.config_changed(); P.mesh_cache.clear()
d2 = P.part_doc(P.asm.comp(cs["id"])); print("Short leaves", d2.leaf_names, round(d2.solid.volume, 1))
assert len(d2.leaf_names) == 2 and abs(d2.solid.volume - (60*40*10 + 1000)) < 1
print("mate still", P.asm.status)
# mass of parent includes everything
import asm_patterns
P.asm.cfg_apply("Default"); P.config_changed()
pr = asm_patterns.assembly_props(P); print("parent mass", round(pr["mass"], 4), "base", round(evaluate.mass_properties(P.part_doc(base).solid, 7850)["mass"], 4), "sub", round(mass_default, 4))
assert abs(pr["mass"] - (evaluate.mass_properties(P.part_doc(base).solid, 7850)["mass"] + mass_default)) < 1e-6
# loops and self-insertion
P.path = os.path.join(tmp, "parent.gpa"); P.save()
w_sub.insert_files([P.path]); print("loop refused:", len(w_sub.asm.components))
assert all(not c["path"].endswith("parent.gpa") for c in w_sub.asm.components)
P.insert_files([P.path]); assert len(P.asm.components) == 2
# reload from file
sh3 = gpd_app.AppShell([P.path]); P3 = sh3.cur(); print("reloaded", P3.asm.status, [c["name"] for c in P3.asm.components])
d3 = P3.part_doc(P3.asm.components[1]); assert getattr(d3, "is_sub", False)
# mirror copy of the sub-assembly
asm_patterns.start(P3, "mirror"); P3.pat["data"]["seeds"] = [P3.asm.components[1]["id"]]; P3.pat["data"]["plane"] = "Right"; P3.refresh_derived()
print("mirror copies", len([c for c in P3.asm.components if c.get("derived")]))
# nested: put the parent in another assembly
sh4 = gpd_app.AppShell([]); T = sh4.new_assembly(); T.insert_files([P.path]); dd = T.part_doc(T.asm.components[0])
print("nested leaves", dd.leaf_names, round(dd.solid.volume, 1)); assert len(dd.leaf_names) == 2
print("SUBASM OK")
