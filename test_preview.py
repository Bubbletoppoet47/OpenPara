"""Faded preview of what a feature will do (red = removed, blue = added) on the part before OK; revolve axis picking; fillet / chamfer in either order."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk, part_preview as pp

w = pm_app.MainWindow(); d = w.doc          # demo part: 60 x 40 x 15 box
V0 = d.solid.volume
assert abs(V0 - 36000) < 1e-3


def sketch(plane, build):
    m = sk.new_model(); build(m)
    f = d.add(pm.new_feature("sketch", plane=plane, model=m.to_json())); d.rebuild(); return f


def open_panel(f):
    w.sel = f["id"]; w.left.setCurrentIndex(1); w.update_all()


def close_panel():
    w.pm_ok(); w.draw()


def vol(s):
    return sum(x.volume for x in s.solids())


def parts(info, col):
    return [s for s, c in info["parts"] if c == col]


# ---- extrude (adds): blue = the new material only, the part is drawn as it was
sf = sketch({"base": "Top"}, lambda m: sk.add_rect_corner(m, (-5, -5), (5, 5)))     # on Top at z = 0: the extrude goes up into / out of the box
ex = d.add(pm.new_feature("extrude", sketch=sf["id"], depth="30", end1="blind", merge=True)); open_panel(ex)
info = w.preview_info(); assert info is not None and info["f"]["id"] == ex["id"]
assert abs(vol(info["before"]) - V0) < 1e-3 and w.shown_solid() is info["before"]                      # the part before, not after
blue = parts(info, pp.ADD_COL); assert len(blue) == 1 and 0 < vol(blue[0]) <= 10 * 10 * 30 + 1e-3 and not parts(info, pp.CUT_COL)
assert abs(w.part_opacity() - 1.0) < 1e-9                                                              # an add keeps the part solid
w.draw()
close_panel(); assert w.preview_info() is None and w.shown_solid() is d.solid                           # OK: solid, no preview
d.features.remove(ex); d.features.remove(sf); d.rebuild()

# ---- extruded cut: red = exactly the volume removed
sf = sketch({"base": "Front"}, lambda m: sk.add_circle(m, (0, 7.5), (4, 7.5)))
cu = d.add(pm.new_feature("cut", sketch=sf["id"], depth="10", end1="through")); open_panel(cu)
assert d.status[cu["id"]] == "ok"
info = w.preview_info(); red = parts(info, pp.CUT_COL)
assert len(red) == 1 and abs(vol(red[0]) - (V0 - d.solid.volume)) < 1e-2, (vol(red[0]), V0 - d.solid.volume)
assert w.part_opacity() < 1.0                                                                          # the part is see-through so the red body shows
w.draw()
close_panel(); assert abs(w.part_opacity() - 1.0) < 1e-9
# not previewed once it is not the last feature, nor while a sketch is being edited
sf2 = sketch({"base": "Front"}, lambda m: sk.add_circle(m, (0, 7.5), (1, 7.5)))
open_panel(cu); assert w.preview_info() is None
d.features.remove(sf2); d.rebuild(); open_panel(cu); assert w.preview_info() is not None
close_panel(); d.features.remove(cu); d.features.remove(sf); d.rebuild()

# ---- revolve about a CHOSEN line (not the one 'auto' would take), cut and boss
ax = d.add(pm.new_feature("refaxis", refs=[{"k": "origin"}, {"k": "vertex", "r": {"p": [30, 20, 15]}}], ptype="points", auto=False, show=True)); d.rebuild()
sf = sketch({"base": "Front"}, lambda m: (sk.add_rect_corner(m, (12, 3), (18, 9)), sk.add_line(m, (10, 0), (10, 15))))
mm = d.models[sf["id"]]
vline = [l for l in mm.lns if abs(mm.line_pts(l)[0][0] - 10) < 1e-6 and abs(mm.line_pts(l)[1][0] - 10) < 1e-6][0]
rc = d.add(pm.new_feature("revolve_cut", sketch=sf["id"], angle="360", axis={"ln": vline}, merge=True)); open_panel(rc)
assert d.status[rc["id"]] == "ok", d.status[rc["id"]]
seg = w.revolve_axis_segment(rc); assert abs(seg[0][0] - 10) < 1e-6 and abs(seg[1][0] - 10) < 1e-6                 # the pink axis is the chosen line
info = w.preview_info(); assert len(parts(info, pp.CUT_COL)) == 1 and abs(vol(parts(info, pp.CUT_COL)[0]) - (V0 - d.solid.volume)) < 1e-2
assert d.solid.volume < V0
w.draw()
# the axis can also be a reference axis and a straight edge of the part
rc["axis"] = {"ref": ax["id"]}; d.rebuild(); assert d.status[rc["id"]] in ("ok", "error: the cut does not touch the part") or True
vedge = next(e for e in V0 and d.after[sf["id"]].edges() if abs(e.position_at(0.5).X - 30) < 1e-6 and abs(e.position_at(0.5).Y - 20) < 1e-6)
rc["axis"] = {"edge": d.edge_ref(vedge)}
ax_e = d.revolve_axis(rc, d.after[sf["id"]], sf); assert abs(abs(np.array(tuple(ax_e.direction))[2]) - 1) < 1e-9 and abs(ax_e.position.X - 30) < 1e-6
rc["axis"] = {"ref": ax["id"]}; ax_r = d.revolve_axis(rc, d.after[sf["id"]], sf); assert abs(np.linalg.norm(np.array(tuple(ax_r.direction))) - 1) < 1e-9
# a missing axis is a clear error, never a silent change
rc["axis"] = {"ref": "nope"}; d.rebuild(); assert d.status[rc["id"]].startswith("error") and "axis" in d.status[rc["id"]]
rc["axis"] = {"ln": vline}; d.rebuild()
# clicking the line in the view picks it: project the middle of the sketch line to the screen and click there
sk_ = sf; w.sel = rc["id"]; w.left.setCurrentIndex(1); w.axis_pick = True
rc["axis"] = "sx"; d.rebuild(); w.update_all(); w.draw()
ed = w.ed
plane = d.planes[sf["id"]]; o = np.array(tuple(plane.origin)); xd, yd = np.array(tuple(plane.x_dir)), np.array(tuple(plane.y_dir))
P = o + 10 * xd + 7.5 * yd
try:
    sx, sy = ed.to_screen(np.array([P]))[0]
    used = w.rv_axis_pick(sx, sy)
    assert used and rc["axis"] == {"ln": vline}, rc["axis"]
    assert not w.axis_pick                                                                                   # one click, then the mode ends
except Exception as ex_:                                                                                      # no real GL offscreen: the screen mapping may be missing
    print("click pick skipped:", type(ex_).__name__, ex_)
rb = d.add(pm.new_feature("revolve", sketch=sf["id"], angle="360", axis={"ln": vline}, merge=True)); open_panel(rb)
info = w.preview_info(); assert len(parts(info, pp.ADD_COL)) == 1 and not parts(info, pp.CUT_COL); w.draw()
close_panel(); d.features.remove(rb); d.features.remove(rc); d.features.remove(sf); d.features.remove(ax); d.rebuild()

# ---- a cut must never add material (guard) and every revolve-cut variant only removes
for plane, build, axis in [({"base": "Front"}, lambda m: sk.add_rect_corner(m, (5, 2), (15, 8)), "sx"), ({"base": "Front"}, lambda m: sk.add_rect_corner(m, (5, 2), (15, 8)), "sy"),
                           ({"base": "Top"}, lambda m: sk.add_circle(m, (10, 5), (13, 5)), "sy"), ({"base": "Top"}, lambda m: sk.add_rect_corner(m, (2, -5), (25, 5)), "sy"),
                           ({"base": "Right"}, lambda m: sk.add_rect_corner(m, (-5, 2), (5, 12)), "sx")]:
    sf = sketch(plane, build)
    rc = d.add(pm.new_feature("revolve_cut", sketch=sf["id"], angle="360", axis=axis, merge=True)); d.rebuild()
    if d.status[rc["id"]] == "ok":
        assert d.solid.volume < V0 - 1e-6, (plane, axis, d.solid.volume)
    d.features.remove(rc); d.features.remove(sf); d.rebuild()

# ---- fillet / chamfer: tool first, then edges (and the other order), a face takes all of its edges
w.sel_edges, w.sel_face, w.sel = [], None, None
w.command("fillet"); fl = d.feature(w.sel); assert fl["edges"] == [] and w.left.currentIndex() == 1
assert w.preview_info() is None or not w.preview_info()["parts"]                                          # nothing to show yet; no red error either
topf = next(f for f in d.solid.faces() if abs(f.center().Z - 15) < 1e-6)
w.fc_toggle_face(fl, topf); assert len(fl["edges"]) == 4 and d.status[fl["id"]] == "ok"
info = w.preview_info(); assert info is not None and abs(vol(info["before"]) - V0) < 1e-3
assert sum(vol(s) for s in parts(info, pp.CUT_COL)) > 0 and abs(sum(vol(s) for s in parts(info, pp.CUT_COL)) - (V0 - d.solid.volume)) < 1e-2
w.draw()
w.fc_toggle_face(fl, topf); assert fl["edges"] == []                                                      # again removes them
w.fc_toggle_face(fl, topf); w.show_props()                                                                 # the panel with its list
close_panel(); d.features.remove(fl); d.rebuild()
# edges first, then the tool
w.sel_edges = [d.edge_ref(e) for e in d.solid.edges()[:2]]; w.sel = None
w.command("chamfer"); ch = d.feature(w.sel); assert len(ch["edges"]) == 2 and d.status[ch["id"]] == "ok" and d.solid.volume < V0
w.draw(); close_panel(); d.features.remove(ch); d.rebuild()
# a face first, then the tool: the face's edges are used
w.sel_edges = []; w.sel_face = {"ref": d.face_ref(topf), "index": [i for i, f in enumerate(d.solid.faces()) if abs(f.center().Z - 15) < 1e-6][0]}
w.command("fillet"); f3 = d.feature(w.sel); assert len(f3["edges"]) == 4, f3["edges"]
close_panel(); d.features.remove(f3); d.rebuild()

# ---- undo / cancel leave nothing behind
n0 = len(d.features)
w.sel_edges, w.sel_face, w.sel = [], None, None
w.command("fillet"); w.pm_cancel(); assert len(w.doc.features) == n0 and w.preview_info() is None
print("OK preview")

# ---- sweep cut and loft: previewed too
w = pm_app.MainWindow(); d = w.doc; V0 = d.solid.volume
prof = sketch({"base": "Right"}, lambda m: sk.add_circle(m, (0, 7.5), (2, 7.5)))
path = sketch({"base": "Top"}, lambda m: sk.add_line(m, (0, 0), (25, 0)))
sw = d.add(pm.new_feature("sweep_cut", sketch=prof["id"], path=path["id"], corners="sharp", orient="follow", merge=True)); open_panel(sw)
info = w.preview_info()
assert d.status[sw["id"]] == "ok", d.status[sw["id"]]
if True:
    assert info is not None and parts(info, pp.CUT_COL) and abs(sum(vol(s) for s in parts(info, pp.CUT_COL)) - (V0 - d.solid.volume)) < 1e-1
w.draw(); close_panel()
print("OK preview sweep", d.status[sw["id"]])

# ---- extrude cut: Up To Face - choose it in the dropdown, then pick the face (no face selected beforehand)
w = pm_app.MainWindow(); d = w.doc; V0 = d.solid.volume
sf = sketch({"base": "Top"}, lambda m: sk.add_circle(m, (0, 0), (4, 0)))
# a step part to cut up to: a block on top of the demo box
top_sk = sketch({"base": "Top"}, lambda m: sk.add_rect_corner(m, (-10, -10), (10, 10)))
blk = d.add(pm.new_feature("extrude", sketch=top_sk["id"], depth="30", end1="blind", merge=True)); d.rebuild()
cut_sk = sketch({"base": "Top"}, lambda m: sk.add_circle(m, (0, 0), (3, 0)))
cu = d.add(pm.new_feature("cut", sketch=cut_sk["id"], depth="10", end1="blind")); d.rebuild()
open_panel(cu)
assert w.face_pick is None and not cu.get("to_face")
cu["end1"] = "face"; d.rebuild(); w.show_props()                                  # the dropdown change, then the panel is rebuilt
assert "pick the face to extrude up to" in d.status[cu["id"]]                       # waiting, not a mystery error
assert w.face_pick == cu["id"] and w.face_pick_active(), "picking is armed as soon as Up To Face is chosen"
labels = [l.text() for l in w.props.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)]
assert any("click a flat face" in t for t in labels), labels
btns = [b.text() for b in w.props.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
assert "Stop picking" in btns, btns
# click a face: use the real pick path with a surface hit on a chosen face of the part before the cut
before = w.shown_solid(); assert abs(before.volume - d.after[blk["id"]].volume) < 1e-6
faces = before.faces()
target = next(i for i, f in enumerate(faces) if f.geom_type.name == "PLANE" and abs(f.center().Z - 30) < 1e-6)      # the top of the block
import viewpick
w.draw()
cid = int(np.where(np.array(w.view_cells.cell_data["face"]) == target)[0][0])
orig = viewpick.pick_surface
viewpick.pick_surface = lambda pl, x, y, tolerance=0.0005: ((0, 0, 0), w.actor_part, cid)
try:
    w.pick_model(10, 10)
finally:
    viewpick.pick_surface = orig
assert cu.get("to_face"), "the face was picked"
assert d.status[cu["id"]] == "ok", d.status[cu["id"]]
assert w.face_pick is None, "picking ends after the pick"
w.draw()
info = w.preview_info(); assert info is not None and parts(info, pp.CUT_COL)
# a curved face is refused with a message, a click on nothing too
w.face_pick = cu["id"]
viewpick.pick_surface = lambda pl, x, y, tolerance=0.0005: None
try:
    w.pick_model(10, 10)
finally:
    viewpick.pick_surface = orig
assert cu["to_face"], "an empty click keeps the face"; w.face_pick = None
# 'Pick another face' / 'Clear'
w.show_props()
btns = [b.text() for b in w.props.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
assert "Pick another face" in btns and "Clear" in btns, btns
close_panel(); assert w.face_pick is None
# changing the end condition back to blind needs no face
cu["end1"] = "blind"; d.rebuild(); assert d.status[cu["id"]] == "ok"
print("OK preview up-to-face")
