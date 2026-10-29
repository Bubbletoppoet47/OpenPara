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
sh = gpd_app.AppShell([pa]); w = sh.new_assembly(); w.insert_files([pa, pb]); A = w.asm
c0, c1 = A.components[:2]
def faces(c):
    s = w.solid_of(c); fs = s.faces()
    return {k: i for k, i in [("top", max(range(len(fs)), key=lambda i: fs[i].center().Z)), ("bot", min(range(len(fs)), key=lambda i: fs[i].center().Z))]}
def R(c, i):
    f = w.solid_of(c).faces()[i]; return {"c": c["id"], "k": "face", "r": am.face_ref(f)}
w.mate_start()
w.add_mate_ref(R(c0, faces(c0)["top"]), {"cid": c0["id"], "kind": "face", "idx": faces(c0)["top"], "label": "Face"})
w.add_mate_ref(R(c1, faces(c1)["bot"]), {"cid": c1["id"], "kind": "face", "idx": faces(c1)["bot"], "label": "Face"})
w.mate_ok(); A = w.asm; c0, c1 = A.components[:2]
z0 = c1["pos"][2]; print("z after mate", z0)
# tree: checkbox, no tab jump
mt = [i for i in range(w.tree.topLevelItemCount())]
def mate_item():
    root = w.tree.topLevelItem(0)
    for i in range(root.childCount()):
        for j in range(root.child(i).childCount()):
            it = root.child(i).child(j)
            if (it.data(0, Qt.ItemDataRole.UserRole) or ("",))[0] == "mate": return it
it = mate_item(); assert it.checkState(0) == Qt.CheckState.Checked
w.left.setCurrentIndex(0); w.tree.setCurrentItem(it); app.processEvents()
assert w.left.currentIndex() == 0, "selecting a mate must not switch tabs"
it.setCheckState(0, Qt.CheckState.Unchecked); app.processEvents(); app.processEvents()
assert w.asm.mates[0]["suppressed"] is True; print("suppressed via checkbox")
it = mate_item(); assert it.checkState(0) == Qt.CheckState.Unchecked
it.setCheckState(0, Qt.CheckState.Checked); app.processEvents(); app.processEvents()
assert not w.asm.mates[0]["suppressed"]
# edit: panel populated, highlights present
A = w.asm; mid = A.mates[0]["id"]
w.mate_edit_start(mid)
assert w.mode == "mate" and len(w.mate_sel) == 2 and w.mate_type == "coincident", (w.mode, w.mate_sel)
assert all(s["idx"] >= 0 for s in w.mate_sel) and len(w.hi_actors) == 2, len(w.hi_actors)
assert len(w.asm.mates) == 0
print("edit populated", [s["label"] for s in w.mate_sel], "highlights", len(w.hi_actors))
# remove one pick -> highlight goes away
w.add_mate_ref(w.mate_sel[0]["ref"], w.mate_sel[0]); assert len(w.mate_sel) == 1 and len(w.hi_actors) == 1
print("after removing one: highlights", len(w.hi_actors))
w.mate_cancel(); assert w.mode is None and len(w.asm.mates) == 1 and w.asm.mates[0]["id"] == mid
# edit to distance 7 and OK
w.mate_edit_start(mid); w.set_mate_type("distance"); w.mate_opts["value"] = 7.0; w.mate_preview(); assert not w.mate_error, w.mate_error
w.mate_ok(); A = w.asm; m = A.mates[0]; print("edited", m["id"], m["type"], m.get("value"), round(A.components[1]["pos"][2] - z0, 3))
assert m["id"] == mid and m["type"] == "distance" and abs(abs(A.components[1]["pos"][2] - z0) - 7) < 1e-3
w.do_undo(); assert w.asm.mates[0]["type"] == "coincident"; print("undo ok")
# unchanged edit keeps the mate as it was
w.mate_edit_start(w.asm.mates[0]["id"]); w.mate_ok(); assert w.asm.mates[0]["type"] == "coincident" and abs(w.asm.components[1]["pos"][2] - z0) < 1e-6
# delete
w.tree.setCurrentItem(mate_item()); w.delete_mate(w.asm.mates[0]["id"]); assert len(w.asm.mates) == 0
w.do_undo(); assert len(w.asm.mates) == 1
print("MATE EDIT OK")
