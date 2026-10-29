import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm
w = pm_app.MainWindow()
d = w.doc
print("start:", d.status, round(d.solid.volume))
# select the top face programmatically (as a click would) and sketch on it
idx = max(range(len(d.solid.faces())), key=lambda i: d.solid.faces()[i].center().Z)
w.sel_face = {"ref": d.face_ref(d.solid.faces()[idx]), "index": idx}
w.command("sketch"); sk = d.feature(w.sel)
sk["entities"] = [{"kind": "circle", "cx": 0, "cy": 0, "d": "HoleD"}]; sk["model"] = None
w.update_all()
w.command("cut"); cut = d.feature(w.sel); cut["through"] = True; w.update_all()
print("after hole:", d.status, round(d.solid.volume))
assert d.status[cut["id"]] == "ok"
w.command("fillet"); fl = d.feature(w.sel)
solid = w.shown_solid()
edge = [e for e in solid.edges() if e.geom_type.name == "LINE" and abs(e.tangent_at(0.5).Z) > .9][0]
fl["edges"] = [d.edge_ref(edge)]; fl["size"] = "3"; w.update_all()
print("fillet:", d.status[fl["id"]])
w.doc.params["Length"] = "80"; w.update_all()
print("Length=80:", set(d.status.values()), round(d.solid.volume))
w.set_rollback(sk["id"]); print("rollback:", [d.status[f["id"]] for f in d.features]); w.set_rollback(None)
w.do_undo(); w.do_redo(); d = w.doc
w.doc.params["Height"] = "-1"; w.update_all(); print("bad:", [d.status[f["id"]][:30] for f in d.features][:3])
# nearest edge pick
w.doc.params["Height"] = "15"; w.update_all()
root = w.tree.topLevelItem(0)
print("tree:", [root.child(i).text(0) for i in range(root.childCount())])
w.command("sketch") if False else None
w.pm_ok(); w.leave_sketch()
w.sel_plane = "Front"; w.sel_face = None; w.command("sketch"); n = len(w.doc.features); w.pm_cancel(); print("cancel removed new sketch:", len(w.doc.features) == n - 1)
print("OK")
