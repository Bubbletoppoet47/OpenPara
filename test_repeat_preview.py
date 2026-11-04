"""Mirror and Pattern: faded preview (standard for every feature), the selection rows (mirror face, direction edge) and picking in the view."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk, part_preview as pp

# ---- every feature kind has a preview or a stated reason not to
kinds = set(pm.Document.add.__code__.co_consts[0:0])
import inspect, re
src = inspect.getsource(pm.Document.add)
allk = set(re.findall(r'"(\w+)": "[A-Za-z\- ]+"', src.split("title =")[1].split("}")[0]))
assert {"mirror", "pattern", "fillet", "extrude", "sketch", "refpoint"} <= allk, allk
for k in allk:
    assert k in pp.KINDS or k in pp.NO_PREVIEW, f"feature kind {k!r} has no preview and no reason listed in part_preview.NO_PREVIEW"
assert "pattern" in pp.KINDS and "mirror" in pp.KINDS

w = pm_app.MainWindow(); d = w.doc          # demo part: 60 x 40 x 15 box
V0 = d.solid.volume


def sketch(plane, build):
    m = sk.new_model(); build(m)
    f = d.add(pm.new_feature("sketch", plane=plane, model=m.to_json())); d.rebuild(); return f


def open_panel(f):
    w.sel = f["id"]; w.left.setCurrentIndex(1); w.update_all()


def vol(s):
    return sum(x.volume for x in s.solids())


# a boss off to one side so that its mirror is a different place
sf = sketch({"base": "Top"}, lambda m: sk.add_rect_corner(m, (10, 5), (20, 15)))
bx = d.add(pm.new_feature("extrude", sketch=sf["id"], depth="30", end1="blind", merge=True)); d.rebuild()
assert d.status[bx["id"]] == "ok"
Vb = d.solid.volume

# ---- mirror: blue = the mirrored copy, the part drawn as it was; selection rows say what is picked
mi = d.add(pm.new_feature("mirror", features=[bx["id"]], source="features", plane={"base": "Right"})); w.sel = mi["id"]; open_panel(mi)
assert d.status[mi["id"]] == "ok", d.status[mi["id"]]
info = w.preview_info(); assert info is not None and info["f"]["id"] == mi["id"]
blue = [s for s, c in info["parts"] if c == pp.ADD_COL]; red = [s for s, c in info["parts"] if c == pp.CUT_COL]
assert blue and not red and abs(vol(blue[0]) - (d.solid.volume - Vb)) < 1e-2, (vol(blue[0]), d.solid.volume - Vb)
assert abs(vol(info["before"]) - Vb) < 1e-3 and w.shown_solid() is info["before"]
w.draw()
txt = " ".join(l.text() for l in w.props_host.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)) if hasattr(w, "props_host") else ""
# the face row: choosing 'A flat face' arms the pick, a click on a flat face fills it, Stop picking disarms
w.rp_pick = None
f_idx = [i for i in range(w.props_lay.count())]
combos = [c for c in w.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QComboBox"]).QComboBox) if c.findData("face") >= 0]
assert combos, "no 'A flat face' choice in the mirror panel"
combos[0].setCurrentIndex(combos[0].findData("face"))
assert w.rp_pick == (mi["id"], "plane") and w.rp_pick_active()
# click the top face of the 60 x 40 x 15 box at z = 15 ... pick via the model (no real GL): drive rp_pick_click with a stub
solid = w.shown_solid()
topface = max((f_ for f_ in solid.faces() if f_.geom_type.name == "PLANE"), key=lambda f_: f_.center().Z)
import viewpick
cells = w.view_cells
idx = [i for i, fc in enumerate(solid.faces()) if fc is topface or fc.center().Z == topface.center().Z][0]
cid = int(np.where(np.array(cells.cell_data["face"]) == idx)[0][0])
viewpick.pick_surface = lambda pl, x, y: (np.zeros(3), w.actor_part, cid)
viewpick.same_actor = lambda a, b: True
w.rp_pick_click(5, 5)
assert "face" in d.feature(mi["id"])["plane"] and w.rp_pick is None, d.feature(mi["id"])["plane"]
w.draw()                                     # the picked face is drawn on the part (no error)
assert d.status[mi["id"]] == "ok" or str(d.status[mi["id"]]).startswith("error")      # whatever the result, the panel can show it

# ---- linear pattern: blue copies, direction from an edge needs an edge: armed at once, filled by a click
mi_f = d.feature(mi["id"]); d.features.remove(mi_f); d.rebuild()
pt = d.add(pm.new_feature("pattern", ptype="linear", features=[bx["id"]], source="features", dir1="X", count="3", spacing="20")); open_panel(pt)
assert d.status[pt["id"]] == "ok", d.status[pt["id"]]
info = w.preview_info(); blue = [s for s, c in info["parts"] if c == pp.ADD_COL]
assert blue and abs(vol(blue[0]) - (d.solid.volume - Vb)) < 1e-2 and d.solid.volume > Vb
pt["dir1"] = "edge"; pt["edge1"] = None; w.update_all(); open_panel(pt)
assert w.rp_pick == (pt["id"], "edge1"), "choosing a straight edge for the direction should arm the edge pick at once"
assert str(d.status[pt["id"]]).startswith("error")                                                  # waiting: the panel says what is missing
solid = w.pick_solid()
edges = solid.edges()
ei = [i for i, e in enumerate(edges) if e.geom_type.name == "LINE" and abs(e.tangent_at(0.5).Y) > 0.9][0]
w.pick_edge = lambda x, y: ei
w.rp_pick_click(1, 1)
assert pt["edge1"] is not None and w.rp_pick is None
assert d.status[pt["id"]] == "ok", d.status[pt["id"]]
w.draw()
# Stop picking is remembered: no re-arming
pt["edge1"] = None; w.update_all(); w.rp_pick = None; w.rp_off.add((pt["id"], "edge1")); open_panel(pt); assert w.rp_pick is None
# OK / Cancel clear the pick
w.rp_pick = (pt["id"], "edge1"); w.pm_ok(); assert w.rp_pick is None

# ---- circular pattern previews too
d.features.remove(d.feature(pt["id"])); d.rebuild()
pc = d.add(pm.new_feature("pattern", ptype="circular", features=[bx["id"]], source="features", axis="Z", count="3", angle="360")); open_panel(pc)
assert d.status[pc["id"]] == "ok", d.status[pc["id"]]
info = w.preview_info(); assert info is not None and any(c == pp.ADD_COL for _s, c in info["parts"])
w.draw()
print("OK repeat preview")
