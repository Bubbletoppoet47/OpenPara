import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication, QCheckBox
app = QApplication([])
import pm_app, sk_tools as sk
w = pm_app.MainWindow(); w.sel_plane = "Front"; w.command("sketch"); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0); m = ed.m
# a rectangle with nothing on it: all four corners free in the plane (two arrows each)
sk.add_rect_corner(m, (10, 10), (30, 20)); rep = sk.solve_model(m)
corners = [p for p in m.pts if p != 0]
assert set(rep.free_dirs) >= set(corners), rep.free_dirs
assert all(len(rep.free_dirs[p]) == 2 for p in corners)
# a line hooked to the origin and kept horizontal: the free end slides along the line -> one (double headed) direction, along x
w2 = pm_app.MainWindow(); w2.sel_plane = "Front"; w2.command("sketch"); e2 = w2.ed; e2.size_fn = lambda: (1000.0, 700.0); mm = e2.m
lid = sk.add_line(mm, (0, 0), (10, 0)); a, b = mm.lns[lid]
sk.con(mm, "coincident", [("pt", a), ("pt", 0)]); r2 = sk.solve_model(mm)
free_end = b
assert list(r2.free_dirs) == [free_end], r2.free_dirs
d = r2.free_dirs[free_end]; assert len(d) == 1 and abs(abs(d[0][0]) - 1) < 1e-6 and abs(d[0][1]) < 1e-6, d
# a length dimension fixes it: no free points, no arrows
sk.con(mm, "dim_len", [("ln", lid)], value=10.0); r3 = sk.solve_model(mm)
assert r3.dof == 0 and not r3.free_dirs, (r3.dof, r3.free_dirs)
# the origin is never listed
assert 0 not in r2.free_dirs
# drawing: toggle on adds arrows for the points only; lines keep the colours they always had
ed.rep if False else None
w.doc.reports[w.sel] = rep; w.free_motion = False; ed.redraw(); n_off = (len(ed.actors) + len(ed.geo_actors) + sum(len(v) for v in ed.dim_actors.values()))
w.free_motion = True; ed.redraw(); n_on = (len(ed.actors) + len(ed.geo_actors) + sum(len(v) for v in ed.dim_actors.values()))
assert n_on > n_off
# the check box sits right under the blue DOF text of the sketch table
w.free_motion = False; w.update_all()
boxes = [c for c in w.findChildren(QCheckBox) if c.text() == "Show free motion"]
assert boxes, "no Show free motion box"
lay = boxes[0].parentWidget().layout(); idx = lay.indexOf(boxes[0]); assert idx > 0
prev = lay.itemAt(idx - 1).widget(); assert prev is not None and "efined" in prev.text() or "CONFLICT" in prev.text(), prev.text()
boxes[0].setChecked(True); assert w.free_motion
print("OK free motion")
