import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm
w = pm_app.MainWindow(); d = w.doc; ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
sk = [f for f in d.features if f["kind"] == "sketch"][0]
print("sketch used by a feature -> shown?", w.sketch_shown(sk)); assert not w.sketch_shown(sk)
w.sel = sk["id"]; assert not w.sketch_shown(sk)                   # selecting does not show it (its checkbox decides)
w.sel = None
sk["show"] = True; assert w.sketch_shown(sk); sk["show"] = None
# tree checkbox
def find(kind, key=None):
    root = w.tree.topLevelItem(0)
    for i in range(root.childCount()):
        it = root.child(i)
        k = it.data(0, Qt.ItemDataRole.UserRole)
        if k and k[0] == kind and (key is None or k[1] == key): return it
        for j in range(it.childCount()):
            c = it.child(j); k = c.data(0, Qt.ItemDataRole.UserRole)
            if k and k[0] == kind and (key is None or k[1] == key): return c
sit = find("feature", sk["id"]); print("sketch item checkable:", bool(sit.flags() & Qt.ItemFlag.ItemIsUserCheckable), sit.checkState(0))
sit.setCheckState(0, Qt.CheckState.Checked); print("after tick:", sk.get("show"), w.sketch_shown(sk)); assert sk["show"] is True
pit = find("plane", "Top"); pit.setCheckState(0, Qt.CheckState.Unchecked); w.draw(); print("planes drawn:", sorted(w.actor_planes)); assert "Top" not in w.actor_planes
w.set_show("planes", False); assert w.actor_planes == {}; w.set_show("planes", True)
w.set_show("sketches", False); assert not w.sketch_shown(sk) ; w.set_show("sketches", True)
# fillet preview: the drawn part has the rounding, edges to pick are the ones before it
box_vol = d.solid.volume
top = [e for e in d.solid.edges() if abs(e.center().Z - d.solid.bounding_box().max.Z) < 1e-6 and e.geom_type.name == "LINE"]
w.command("fillet"); f = w.doc.feature(w.sel); f["edges"] = [d.edge_ref(e) for e in top[:2]]; f["size"] = "2"; w.update_all()
print("status", w.doc.status[f["id"]], "shown volume", round(w.shown_solid().volume), "pick solid is the earlier one:", w.pick_solid() is not w.shown_solid())
assert w.doc.status[f["id"]] == "ok" and w.shown_solid().volume < box_vol and w.pick_solid().volume == box_vol
print("edge polys for picking:", len(w.edge_polys), "(pre-fillet has", len(w.pick_solid().edges()), "edges)"); assert len(w.edge_polys) == len(w.pick_solid().edges())
print("OK")
