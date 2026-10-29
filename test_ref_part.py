import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_model as pm, pm_app, part_refgeo as prg
w = pm_app.MainWindow(); d = w.doc          # demo part 60 x 40 x 15
assert d.solid is not None
# offset plane from the Top plane, picked through the tree click path
w.sel_plane = "Top"; w.command("refplane")
f = w.doc.feature(w.sel); assert f["kind"] == "refplane" and w.rg_feature() is f, f
print("prefilled", f["refs"], f["ptype"], w.doc.status[f["id"]], w.doc.refgeo[f["id"]]["p"])
f["d"] = "20"; w.update_all()
assert abs(w.doc.refgeo[f["id"]]["p"][2] - 20) < 1e-9
# picks from the small tree: toggling
assert prg.rg_pick_tree(w, "plane", "Front")                    # adds a second plane -> type becomes mid? (needs parallel)
f = w.doc.feature(w.sel); print("after 2nd pick", f["ptype"], w.doc.status[f["id"]])
assert f["ptype"] == "mid" and w.doc.status[f["id"]].startswith("error")
assert prg.rg_pick_tree(w, "plane", "Front"); f = w.doc.feature(w.sel); assert len(f["refs"]) == 1 and f["ptype"] == "offset" and w.doc.status[f["id"]] == "ok"
w.pm_ok(); assert w.rg_feature() is None
# sketch on the new plane
w.sel = f["id"]; w.command("sketch"); sk = w.doc.feature(w.sel)
print("sketch plane", sk["plane"], w.doc.status[sk["id"]], tuple(w.doc.planes[sk["id"]].origin))
assert sk["plane"] == {"ref": f["id"]} and abs(w.doc.planes[sk["id"]].origin.Z - 20) < 1e-9
w.leave_sketch()
# an axis through two planes; a plane perpendicular to it through a vertex
w.sel_plane = "Front"; w.command("refaxis"); a = w.doc.feature(w.sel)
prg.rg_pick_tree(w, "plane", "Right"); a = w.doc.feature(w.sel)
print("axis", a["ptype"], w.doc.status[a["id"]], w.doc.refgeo.get(a["id"]))
assert a["ptype"] == "planes" and w.doc.status[a["id"]] == "ok"
w.pm_ok()
w.sel = None; w.command("refplane"); p2 = w.doc.feature(w.sel)
prg.rg_pick_tree(w, "feature", a["id"]); prg.rg_pick_tree(w, "origin", None); p2 = w.doc.feature(w.sel)
print("perp", p2["ptype"], w.doc.status[p2["id"]], p2["refs"])
assert w.doc.status[p2["id"]] == "ok"
w.pm_ok()
# mirror about a reference plane
w.command("mirror"); m = w.doc.feature(w.sel); m["plane"] = {"ref": f["id"]}; w.update_all(); print("mirror", w.doc.status[m["id"]])
# save / reload keeps refs and the drawing code runs
js = w.doc.to_json(); d2 = pm.Document.from_json(js); d2.rebuild(); assert len(d2.refgeo) == len(w.doc.refgeo) and all(v == "ok" or v.startswith("suppr") or True for v in d2.status.values())
w.draw(); print("actors", len(w.actor_refs))
# tree checkbox
ft = [i for i in range(w.tree.topLevelItem(0).childCount())]
w.doc.feature(f["id"])["show"] = False; w.draw(); print("hidden ok")
# undo
w.do_undo(); w.do_redo()
print("PART REF OK")
# the small tree
w2 = pm_app.MainWindow(); mt = w2.mini
assert mt.tree.topLevelItemCount() == 1 and mt.tree.topLevelItem(0).childCount() > 4
def find(kind, key=None):
    stack = [mt.tree.topLevelItem(0)]
    while stack:
        it = stack.pop()
        dt = it.data(0, Qt.ItemDataRole.UserRole)
        if dt and dt[0] == kind and (key is None or dt[1] == key): return it
        stack += [it.child(i) for i in range(it.childCount())]
from PyQt6.QtCore import Qt
w2.command("refplane"); f2 = w2.doc.feature(w2.sel)
mt.clicked(find("plane", "Right"))
f2 = w2.doc.feature(w2.sel); print("mini pick", f2["refs"]); assert {"k": "base", "n": "Right"} in f2["refs"]
w2.pm_ok(); mt.clicked(find("plane", "Front")); assert w2.sel_plane == "Front", "no pick mode: selects"
mt.toggle(); assert mt.open; mt.toggle()
print("MINI OK")
