import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se
w = pm_app.MainWindow(); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
d = w.doc
print("start", d.status, round(d.solid.volume), "edge polys", len(w.edge_polys))
assert len(w.edge_polys) >= 12
# --- edge selection in the part view (iso camera): click on the middle of an edge
def px_of(p): return tuple(ed.to_screen(np.array([p]))[0])
mid = lambda poly: (poly[0] + poly[-1]) / 2 if len(poly) == 2 else poly[len(poly) // 2]
top = [i for i, p in enumerate(w.edge_polys) if abs(p[0][2] - 15) < 1e-6 and abs(p[-1][2] - 15) < 1e-6]
print("top edges", len(top))
w.pick_model(*px_of(mid(w.edge_polys[top[0]])))
print("selected:", len(w.sel_edges)); assert len(w.sel_edges) == 1
w.pick_model(*px_of(mid(w.edge_polys[top[1]])), shift=True); assert len(w.sel_edges) == 2
w.pick_model(*px_of(mid(w.edge_polys[top[1]])), shift=True); assert len(w.sel_edges) == 1          # clicking again removes
w.pick_model(*px_of(mid(w.edge_polys[top[1]])), shift=True); assert len(w.sel_edges) == 2
w.command("fillet"); f = d.feature(w.sel) if False else w.doc.feature(w.sel)
print("fillet takes the selection:", len(f["edges"]), w.doc.status[f["id"]]); assert len(f["edges"]) == 2 and w.doc.status[f["id"]] == "ok"
w.pm_ok(); w.do_undo(); w.do_undo() if False else None
# --- selection inside a sketch: sketch on the top face, pick part edges, convert
d = w.doc
w.sel_edges = []
topface = max(range(len(d.solid.faces())), key=lambda i: d.solid.faces()[i].center().Z)
w.sel_face = {"ref": d.face_ref(d.solid.faces()[topface]), "index": topface}
w.command("sketch"); sid = w.sel; assert ed.active
ed.press(*(0, 0)) if False else None
polys = w.edge_polys
topidx = [i for i, p in enumerate(polys) if abs(p[0][2] - 15) < 1e-6 and abs(p[-1][2] - 15) < 1e-6]
# click one of the top edges with the select tool (nothing of the sketch is there)
ed.tool = "select"
ed.press(*px_of(mid(polys[topidx[0]]))); ed.release(*px_of(mid(polys[topidx[0]])))
print("edge picked while sketching:", len(w.sel_edges)); assert len(w.sel_edges) == 1
ed.command_convert(); m = ed.m; print("status:", w.statusBar().currentMessage()); print(w.doc.status, len(w.doc.feature(sid)["model"]))
print("converted:", len(m.lns), "lines, fixed:", sum(1 for c in m.cons if c["type"] == "fixed")); assert len(m.lns) == 1
# face pick -> all its outline edges
w.sel_edges = []; w.sel_face = {"ref": None, "index": topface}
ed.command_convert(); m = ed.m; print("after face convert:", len(m.lns), "lines (joined points:", len(m.pts), ")")
assert len(m.lns) == 4 + 1 - 1 or len(m.lns) >= 4
r = sk_regions = None
import sk_tools as sk
print("regions", len(sk.regions(m)))
# a cut using the converted outline's inner geometry: draw a smaller rect snapping to part corners (vertex snap)
v = ed.model_vertex(*px_of((30, 20, 15)), 12.0); print("vertex snap", v)
assert v is not None
w.leave_sketch()
print("OK")
