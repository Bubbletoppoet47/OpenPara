"""Zoom to Fit (F) in the Part window fits the whole part and the sketches - and, in an open sketch, the sketch - not just the origin planes; the Front / Top / Right planes
and the origin axes grow with the part and the sketches (also while a sketch is drawn); the origin is always inside them.  python test_part_fit.py"""
import faulthandler
faulthandler.dump_traceback_later(170, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_NO_UPDATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import gpd_app
import pm_app
import pm_model as pm
import sk_tools as sk

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def inside(w, pts, margin=0.0):
    """True when every world point is in the view (device pixels of the view), and the biggest spread fills at least half of it."""
    ed = w.ed
    W, H = ed.size_fn()
    px = ed.to_screen(np.atleast_2d(np.asarray(pts, float)))
    inside_ = bool(np.all(px[:, 0] >= -margin) and np.all(px[:, 0] <= W + margin) and np.all(px[:, 1] >= -margin) and np.all(px[:, 1] <= H + margin))
    fill = max((px[:, 0].max() - px[:, 0].min()) / W, (px[:, 1].max() - px[:, 1].min()) / H)
    return inside_, fill


def plane_half(w, nm="Front"):
    b = w.actor_planes[nm].GetBounds()
    return max(b[1] - b[0], b[3] - b[2], b[5] - b[4]) / 2


w = pm_app.MainWindow()
d = w.doc
w.show()
app.processEvents()
d.features.clear()
d.rebuild()
w.update_all()
ok(w.model_bounds() is None and abs(w.plane_size() - 30.0) < 1e-9, "an empty part: no bounds, the planes are 30 mm as they were")

# ---- a big sketch and nothing else: the planes are as big as the sketch
m = sk.new_model()
sk.add_rect_corner(m, (200, 100), (700, 400))
f = d.add(pm.new_feature("sketch", plane={"base": "Front"}, model=m.to_json()))
d.rebuild()
w.sel = f["id"]
w.update_all()
w.draw(fit=True)
b = w.model_bounds()
ok(b is not None and abs(b[0] - 200) < 1e-6 and abs(b[1] - 700) < 1e-6 and abs(b[4] - 100) < 1e-6 and abs(b[5] - 400) < 1e-6, f"the bounds are the sketch's ({[round(x) for x in b]})")
ok(abs(w.plane_size() - 1.25 * 700) < 1e-6, f"the planes cover the sketch and the origin ({w.plane_size()})")
ok(abs(plane_half(w) * 2 - w.plane_size()) < 1e-6, "and that is what is drawn")
ok(w.actor_origin and abs(max(a.GetBounds()[1] for a in w.actor_origin) - 0.45 * w.plane_size()) < 1e-6, "the origin axes grow with them")

# ---- F with the sketch shown (not open): everything in the view
w.fit_view()
cam = w.plotter.camera
corners = [[x, 0, z] for x in (200, 700) for z in (100, 400)]
W_, H_ = max(1, w.plotter.width()), max(1, w.plotter.height())
import types
w.ed.size_fn = lambda: (float(W_), float(H_))
i_, fill = inside(w, corners)
ok(i_ and fill > 0.55, f"F fits the sketch in the view, from the direction it looks (fills {fill:.0%})")

# ---- F inside the sketch editor: the sketch (which lives in an overlay layer the camera reset never saw)
w.enter_sketch(f["id"])
w.ed.size_fn = lambda: (float(W_), float(H_))
wb = w.ed.world_bounds()
ok(wb is not None and abs(wb[1] - 700) < 1e-6 and abs(wb[0] - 200) < 1e-6, f"the open sketch knows its extent (the sketch origin does not count) ({[round(x) for x in wb]})")
w.plotter.camera.SetParallelScale(3.0)                           # zoomed in far: the sketch is out of the view
i_, _ = inside(w, corners)
ok(not i_, "(zoomed far in: the sketch is outside the view)")
w.fit_view()
i_, fill = inside(w, corners)
ok(i_ and fill > 0.55, f"F in the open sketch fits the sketch ({fill:.0%} of the view)")
ok(w.plotter.camera.GetParallelProjection(), "the sketch view stays flat (parallel)")
# the menu action of the program window calls the same thing
w.plotter.camera.SetParallelScale(3.0)
gpd_app.AppShell.zoom_fit(types.SimpleNamespace(cur=lambda: w))
i_, fill = inside(w, corners)
ok(i_ and fill > 0.55, "the View > Zoom to Fit action (F) does it")

# ---- drawing more in the sketch: the planes follow at once; erasing it brings them back
m2 = d.models[f["id"]]
sk.add_rect_corner(m2, (-1500, -50), (-1400, 50))
d.store_sketch(f["id"])
w.update_all(light=True)
ok(abs(w.plane_size() - 1.25 * 2200) < 1e-6, f"the planes' size now takes the new rectangle in ({w.plane_size():.0f})")
ok(abs(plane_half(w) * 2 - w.plane_size()) < 1e-3, f"and the planes in the view follow while drawing ({plane_half(w) * 2:.0f})")
w.fit_view()
i_, fill = inside(w, [[-1500, 0, -50], [700, 0, 400]])
ok(i_ and fill > 0.55, "F fits both rectangles")
w.leave_sketch()
w.draw()
ok(abs(plane_half(w) * 2 - w.plane_size()) < 1e-6, "left the sketch: the planes are drawn at the new size")

# ---- a part: the planes are 0.75 of its size (as before), the origin is always inside; a part far from the origin makes them bigger
d.features.clear()
d.rebuild()
w2 = pm_app.MainWindow()
dd = w2.doc                                         # the demo part: 60 x 40 x 15
w2.update_all(fit=True)
b = dd.solid.bounding_box()
ext = max(max(b.max.X, 0) - min(b.min.X, 0), max(b.max.Y, 0) - min(b.min.Y, 0), max(b.max.Z, 0) - min(b.min.Z, 0))
ok(abs(w2.plane_size() - 0.75 * max(ext, 10)) < 1e-6, f"a part: planes 0.75 of its size, the origin counted ({w2.plane_size():.1f})")
ok(abs(plane_half(w2) * 2 - w2.plane_size()) < 1e-6, "and that is what is drawn")
w2.show()
w2.ed.size_fn = lambda: (float(max(1, w2.plotter.width())), float(max(1, w2.plotter.height())))
w2.plotter.camera.SetPosition(600, 600, 600)
w2.plotter.camera.SetFocalPoint(5, 5, 5)
w2.fit_view()
pts = np.array([[x, y, z] for x in (b.min.X, b.max.X) for y in (b.min.Y, b.max.Y) for z in (b.min.Z, b.max.Z)])
i_, fill = inside(w2, pts)
ok(i_ and fill > 0.55, f"F fits the whole part from the iso view ({fill:.0%})")
ok(not w2.plotter.camera.GetParallelProjection(), "(a perspective camera stays perspective)")
w2.plotter.camera.SetPosition(0, 0, 900)
w2.plotter.camera.SetFocalPoint(0, 0, 0)
w2.plotter.camera.SetViewUp(0, 1, 0)
w2.plotter.camera.ParallelProjectionOn()
w2.fit_view()
i_, fill = inside(w2, pts)
ok(i_ and fill > 0.55, f"and from a flat (parallel) view ({fill:.0%})")

print("FAILED:" if FAILS else "ALL PASSED", FAILS)
sys.exit(1 if FAILS else 0)
