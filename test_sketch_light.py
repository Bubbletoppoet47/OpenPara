"""Sketch edits do not rebuild the feature tree (only the sketch); leaving the sketch / Save / Export / mass properties do.  Dragging a label
rebuilds only that dimension; moving the cursor only the dynamic layer."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, sk_tools as sk, pm_model as pm
w = pm_app.MainWindow(); w.sel_plane = "Front"; w.command("sketch"); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0); m = ed.m
sid = ed.sk_id
sk.add_rect_corner(m, (0, 0), (30, 20)); w.doc.reports[sid] = sk.solve_model(m); w.doc.store_sketch(sid)
w.leave_sketch()
ex = w.doc.add(pm.new_feature("extrude", sketch=sid, depth="10")); w.update_all()
v0 = w.doc.solid.volume; print("v0", v0)
# back into the sketch: add a length dimension of the bottom line with a new size - the part must NOT change until the sketch is left
w.enter_sketch(sid); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0); m = ed.m
lid = [l for l in m.lns if abs(m.line_pts(l)[0][1] - m.line_pts(l)[1][1]) < 1e-9][0]
calls = {"rebuild": 0}
orig = w.doc.rebuild
def counting():
    calls["rebuild"] += 1
    return orig()
w.doc.rebuild = counting
sk.con(m, "dim_len", [("ln", lid)], value=50.0)
ed.commit(lambda mm: None)                 # solve + store + (light) update
assert calls["rebuild"] == 0, "the feature tree was rebuilt while sketching"
assert w.stale and abs(w.doc.solid.volume - v0) < 1e-6, "the part must still be the one from before"
assert w.doc.models[sid] is ed.m and ed.m.cons, "the editor keeps working on the sketch"
# the dimension is drawn at once
assert any(c["type"] == "dim_len" for c in ed.m.cons) and ed.dim_actors
# dragging a label rebuilds only that dimension; the geometry actors stay the very same objects
cid = [c for c in ed.m.cons if c["type"] == "dim_len"][0]["id"]
geo = list(ed.geo_actors); dim_other = dict(ed.dim_actors)
before = ed.dim_actors[cid][:]
ed.redraw_label(cid)
assert ed.geo_actors == geo and ed.dim_actors[cid] != before and len(ed.dim_actors[cid]) == len(before)
ed.redraw_dyn(); assert ed.geo_actors == geo
assert calls["rebuild"] == 0
# leaving the sketch: one rebuild, the part follows the new dimension
w.leave_sketch()
assert calls["rebuild"] == 1 and not w.stale
vol1 = w.doc.solid.volume; orig(); assert abs(vol1 - w.doc.solid.volume) < 1e-6 and abs(vol1 - v0) > 1.0, (vol1, v0)
assert calls["rebuild"] == 1
# Save builds first
w.enter_sketch(sid); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
cid = [c for c in ed.m.cons if c["type"] == "dim_len"][0]["id"]
ed.set_dimension(cid, "40"); assert w.stale and calls["rebuild"] == 1
w.path = os.path.join(tempfile.mkdtemp(), "p.gpd"); w.save(); assert not w.stale and calls["rebuild"] == 2
vol2 = w.doc.solid.volume; orig(); assert abs(vol2 - w.doc.solid.volume) < 1e-6 and abs(vol2 - vol1) > 1.0, (vol2, vol1)
print("OK sketch light")
