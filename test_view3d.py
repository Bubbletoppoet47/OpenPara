"""The 3D view (planning/design/viewport): the settings, the neutral colour, the hover outline, the selected fill, the floor shadow and the geometry selector
(General / Point / Edge / Face / Body) in the part window and in the assembly window.   python test_view3d.py"""
import faulthandler
faulthandler.dump_traceback_later(250, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_NO_UPDATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pyvista as pv
from build123d import Box, Cylinder, Pos, Rot

import gpd_app
import pm_app
import pm_model as pm
import settings
import settings_dialog
import sk_tools as sk
import suggest
import view3d
suggest.attach = lambda *a, **k: None

FAILS = []


def rgb_of(actor):
    """The colour of an actor as (r, g, b) floats, whatever this pyvista gives (a Color, a tuple of 3 or of 4)."""
    return tuple(pv.Color(actor.prop.color).float_rgb)


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


# ---------------------------------------------------------------------------------------------------------------- 1. the settings
settings.reset()
d0 = settings.defaults()
ok(d0["hover"] is True and d0["shadow"] is True, "hover highlight and shadow are on by default")
ok(d0["part_color"] == "#999999", "the part colour is 60 % grey (#999999)")
ok(d0["hover_color"] == "#ff7300" and d0["select_color"] == "#00b4ff", "orange hover outline, blue selected fill")
ok(d0["pick_point_px"] > d0["pick3d_px"] and d0["pick_edge_px"] > d0["pick3d_px"], "a point and an edge have a wider reach than General")
ok(np.allclose(view3d.part_rgb(), 0.6) and abs(view3d.hover_rgb()[0] - 1.0) < 1e-9, "view3d reads the colours from the settings")
settings.set_many({"part_color": "#336699", "hover_color": "nonsense"})
ok(settings.get("part_color") == "#336699" and settings.get("hover_color") == "#ff7300", "a colour is kept, a bad one falls back to the default")
settings.reset()
ok(settings.get("part_color") == "#999999", "reset gives the defaults back")
dlg = settings_dialog.SettingsDialog()
names = [dlg.sections.item(i).text() for i in range(dlg.sections.count())]
ok("3D View" in names and "Picking & Snapping" in names, f"File > Settings has a 3D View page ({names})")
v = dlg.values()
ok(all(k in v for k in ("hover", "shadow", "part_color", "hover_color", "select_color", "pick_point_px", "pick_edge_px")), "the settings window carries every new setting")
dlg.shadow.setChecked(False)
dlg.fields["part_color"].set_value("#445566")
dlg.apply()
ok(settings.get("shadow") is False and settings.get("part_color") == "#445566", "Apply writes the shadow tick and the colour")
dlg.reset_defaults()
dlg.apply()
ok(settings.get("shadow") is True and settings.get("part_color") == "#999999", "Reset to defaults puts them back")

# ---------------------------------------------------------------------------------------------------------------- 2. the pieces
ok(view3d.filter_of("general") == {"face": True, "edge": True, "vertex": True}, "General lets a tool pick all three kinds")
ok(view3d.filter_of("edge") == {"face": False, "edge": True, "vertex": False} and view3d.filter_of("point")["vertex"] and not view3d.filter_of("point")["face"],
   "Edge and Point let a tool pick only that kind")
ok(view3d.filter_of("body") == view3d.filter_of("general"), "Body means nothing to a tool: all three")
ok(view3d.pick_px("point") == settings.get("pick_point_px") and view3d.pick_px("edge") == settings.get("pick_edge_px") and view3d.pick_px("general") == settings.get("pick3d_px"),
   "pick_px gives the reach of each kind")

# a flat face with a square hole: an outline round the face and round the hole; a round face: two circles and no seam
doc = pm.Document()
solid = (Rot(0, 90, 0) * Cylinder(30, 40)) - (Rot(0, 90, 0) * Box(12, 12, 60))
fmesh = {}
for i, vv, t in doc.mesh(solid):
    cells = np.hstack([np.full((len(t), 1), 3), t]).ravel()
    fmesh[i] = pv.PolyData(vv, cells)
kinds = {i: f.geom_type.name for i, f in enumerate(solid.faces())}
cap = next(i for i, k in kinds.items() if k == "PLANE" and fmesh[i].area > 1000)
side = next(i for i, k in kinds.items() if k == "CYLINDER")
ol = view3d.face_outline(fmesh[cap])
ok(ol is not None and ol.n_cells > 8, f"the end face with a hole has an outline ({ol.n_cells if ol is not None else 0} segments)")
conn = ol.connectivity() if ol is not None else None
ok(conn is not None and len(set(np.asarray(conn.cell_data["RegionId"]).tolist())) == 2, "the outline is two loops: the rim and the hole")
ol2 = view3d.face_outline(fmesh[side])
ok(ol2 is not None and len(set(np.asarray(ol2.connectivity().cell_data["RegionId"]).tolist())) == 2, "the round face has two circles and no line along its seam")

# the shadow picture
P = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 5], [10, 0, 5], [10, 10, 5], [0, 10, 5]], float)
T = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
res = view3d.shadow_image(P, T)
ok(res is not None, "a box makes a shadow picture")
rgba, (x0, x1, y0, y1), zf = res
h, w_ = rgba.shape[:2]
ok(zf == 0.0 and x0 < 0 and x1 > 10 and y0 < 0 and y1 > 10, "the picture lies on the floor under the lowest point and is larger than the box")
cx, cy = int((5 - x0) / (x1 - x0) * (w_ - 1)), int((5 - y0) / (y1 - y0) * (h - 1))
ok(rgba[cy, cx, 3] > 60, f"it is dark under the box (alpha {rgba[cy, cx, 3]})")
ok(rgba[0, 0, 3] == 0 and rgba[-1, -1, 3] == 0 and rgba[:, 0, 3].max() == 0, "it fades out before the edge of the picture")
ok(rgba[..., 3].max() <= 0.62 * 255 + 1, "it is a soft shadow, never solid black")
ok(view3d.shadow_image(np.zeros((0, 3)), np.zeros((0, 3), int)) is None, "nothing to shadow gives nothing")

# ---------------------------------------------------------------------------------------------------------------- 3. the part window
w = pm_app.MainWindow()
w.resize(1100, 800)
w.show()
app.processEvents()
d = w.doc
d.features.clear()
d.rebuild()
w.update_all()
m = sk.new_model()
sk.add_rect_corner(m, (-20, -20), (20, 20))
sf = d.add(pm.new_feature("sketch", plane={"base": "Front"}, model=m.to_json()))
d.rebuild()
w.sel = sf["id"]
w.update_all()
w.command("extrude")
fe = w.doc.features[-1]
fe["depth"] = "30"
w.pm_ok()
d.rebuild()
w.sel = None
w.update_all(fit=True)
app.processEvents()
solid = w.shown_solid()
ok(solid is not None and len(solid.faces()) == 6, "a 40 x 40 x 30 box is in the part window")
col = rgb_of(w.actor_part)
ok(np.allclose(col, view3d.part_rgb(), atol=1e-6), f"the part is drawn in the neutral grey {tuple(round(c, 2) for c in col)}")
ok(w.shadow is not None and w.shadow.actor is not None, "a floor shadow is drawn under it")
ok(w.shadow.actor.GetUseBounds() == 0, "the shadow is not counted when the view fits the model")
ok(w.selector is not None and w.selector.kind == "general" and set(w.selector.buttons) == set(view3d.KINDS), "the selector sits beside Show with its five buttons, on General")
settings.set_many({"part_color": "#336699"})
w.settings_changed(["part_color"])                              # (this window is not in a shell, which would pass the news on)
ok(np.allclose(rgb_of(w.actor_part), settings.rgb("part_color"), atol=1e-6), "changing the part colour in Settings redraws the part")
d.display["color"] = (0.9, 0.1, 0.1)
w.draw()
ok(np.allclose(rgb_of(w.actor_part), (0.9, 0.1, 0.1), atol=0.01), "a colour set on the part still wins")
d.display["color"] = None
settings.reset()
w.draw()
settings.set_many({"shadow": False})
w.settings_changed(["shadow"])
ok(w.shadow.actor is None, "Shadow off takes the shadow away")
settings.set_many({"shadow": True})
w.settings_changed(["shadow"])
ok(w.shadow.actor is not None, "Shadow on draws it again")

verts = np.array([tuple(v.center()) for v in solid.vertices()])
scr = w.ed.to_screen(verts)
vx, vy = scr[0]
# near a corner: General picks the point only inside its small reach; Point reaches farther
near_gen = settings.get("pick3d_px") * w.plotter.devicePixelRatioF()
far = (vx + 11 * w.plotter.devicePixelRatioF(), vy)
ok(w.what_is_under(int(vx), int(vy), "general")["kind"] == "point", "General: a corner right under the cursor is a point")
ok(w.what_is_under(int(far[0]), int(far[1]), "point") is not None and w.what_is_under(int(far[0]), int(far[1]), "point")["kind"] == "point",
   "Point: a corner 11 px away is still picked (reach 14)")
g = w.what_is_under(int(far[0]), int(far[1]), "general")
ok(g is None or g["kind"] != "point", "General: the same place is not a point (reach 4)")
# an edge: the middle of one
polys = w.edge_polys
ei = 0
mid = (np.asarray(polys[ei][0]) + np.asarray(polys[ei][-1])) / 2
mx, my = w.ed.to_screen(np.array([mid]))[0]
it = w.what_is_under(int(mx), int(my), "edge")
ok(it is not None and it["kind"] == "edge", "Edge: the middle of an edge is an edge")
ok(w.what_is_under(int(mx), int(my), "face") is None or w.what_is_under(int(mx), int(my), "face")["kind"] == "face", "Face: only a face can come of it, never an edge")
off = (mx, my + 9 * w.plotter.devicePixelRatioF())
ok(w.what_is_under(int(off[0]), int(off[1]), "edge") is not None or w.what_is_under(int(mx), int(my + 9 * w.plotter.devicePixelRatioF()), "edge") is None,
   "Edge reaches 10 px")
# the centre of the biggest visible face
fc = None
for fi, f in enumerate(solid.faces()):
    c = f.center()
    sx, sy = w.ed.to_screen(np.array([[c.X, c.Y, c.Z]]))[0]
    r = w.what_is_under(int(sx), int(sy), "face")
    if r is not None and r["kind"] == "face":
        fc = (sx, sy, r["idx"])
        break
ok(fc is not None, "Face: the middle of a visible face is a face")
ok(w.what_is_under(int(fc[0]), int(fc[1]), "body")["kind"] == "body", "Body: the same place is the whole body")
ok(w.what_is_under(int(fc[0]), int(fc[1]), "point") is None and w.what_is_under(int(fc[0]), int(fc[1]), "edge") is None, "Point and Edge pick nothing in the middle of a face")

# the hover
w.selector.set_kind("general", quiet=True)
w.on_hover(int(fc[0]), int(fc[1]))
ok(w.hover_layer.actor is not None, "the cursor over a face draws its outline")
n_lines = w.hover_layer.actor.GetMapper().dataset.n_cells
ok(n_lines >= 4 and w.hover_layer.actor.GetMapper().dataset.GetNumberOfPolys() == 0, f"it is an outline (lines, {n_lines} segments), not a fill")
ok(np.allclose(rgb_of(w.hover_layer.actor), view3d.hover_rgb(), atol=1e-6), "the outline is in the hover colour")
w.selector.set_kind("point", quiet=True)
w.on_hover(int(fc[0]), int(fc[1]))
ok(w.hover_layer.actor is None, "the cursor where nothing of the chosen kind is takes the outline away")
w.selector.set_kind("general", quiet=True)
w.selector.set_kind("edge", quiet=True)
w.on_hover(int(mx), int(my))
ok(w.hover_layer.actor is not None and w.hover_layer.key[0] == "edge", "Edge: the cursor on an edge lights the edge")
w.selector.set_kind("point", quiet=True)
w.on_hover(int(vx), int(vy))
ok(w.hover_layer.actor is not None and w.hover_layer.key[0] == "point", "Point: the cursor on a corner lights the corner")
w.selector.set_kind("body", quiet=True)
w.on_hover(int(fc[0]), int(fc[1]))
ok(w.hover_layer.actor is not None and w.hover_layer.key[0] == "body", "Body: the cursor on the part tints the whole body")
w.selector.set_kind("face", quiet=True)
w.on_hover(int(fc[0]), int(fc[1]))
settings.set_many({"hover": False})
ok(w.hover_layer.actor is not None, "(turning the setting off acts on the next move)")
w.on_hover(int(fc[0]), int(fc[1]))
ok(w.hover_layer.actor is None, "Hover off: nothing is outlined")
settings.set_many({"hover": True})

# the clicks
w.selector.set_kind("face", quiet=True)
w.pick_model(int(fc[0]), int(fc[1]))
ok(w.sel_face is not None and w.sel_face["index"] == fc[2], "Face: a click selects the face")
w.selector.set_kind("edge", quiet=True)
w.pick_model(int(mx), int(my))
ok(len(w.sel_edges) == 1 and w.sel_face is None, "Edge: a click selects the edge (and lets go of the face)")
w.pick_model(int(fc[0]), int(fc[1]))
ok(w.sel_edges == [] and w.sel_face is None, "Edge: a click that is not on an edge picks nothing")
w.selector.set_kind("point", quiet=True)
w.pick_model(int(vx), int(vy))
ok(len(w.sel_points) == 1 and np.allclose(w.sel_points[0]["pt"], verts[0]), "Point: a click selects the corner")
ok("Point selected" in w.statusBar().currentMessage(), "and the status line gives its coordinates")
w.pick_model(int(vx), int(vy))
ok(w.sel_points == [], "a second click on the same point lets go of it")
w.selector.set_kind("body", quiet=True)
w.pick_model(int(fc[0]), int(fc[1]))
ok(w.sel_body is True, "Body: a click selects the whole part")
w.selector.set_kind("general", quiet=True)
w.pick_model(int(fc[0]), int(fc[1]))
ok(w.sel_face is not None and w.sel_body is False, "General: as before, a click on a face selects the face (and lets go of the body)")
w.pick_model(int(mx), int(my))
ok(len(w.sel_edges) == 1, "General: a click on an edge selects the edge, as before")

# tools and sketches
w.selector.set_kind("face", quiet=True)
w.measure_toggle()
ok(w.selector.kind == "general", "Measure puts the selector back to General")
w.measure_stop()
w.selector.set_kind("edge", quiet=True)
ok(w.sel_kind() == "edge", "(the selector decides in the normal mode)")
w.selector.set_kind("general", quiet=True)

# ---------------------------------------------------------------------------------------------------------------- 4. the assembly window
tmp = tempfile.mkdtemp()
paths = []
for nm, size in (("a", 40), ("b", 25), ("c", 30)):
    dd = pm.Document()
    s = dd.add(pm.new_feature("sketch", plane={"base": "Top"}))
    dd.rebuild()
    mm = dd.models[s["id"]]
    sk.add_rect_corner(mm, (0, 0), (size, size))
    sk.solve_model(mm)
    dd.store_sketch(s["id"])
    dd.add(pm.new_feature("extrude", sketch=s["id"], depth="20"))
    dd.rebuild()
    p = os.path.join(tmp, nm + ".gpd")
    open(p, "w").write(dd.to_json())
    paths.append(p)
sh = gpd_app.AppShell()
sh.new_assembly()
aw = sh.tabs.currentWidget()
aw.resize(1100, 800)
aw.insert_files(paths)
aw.update_all(fit=True)
app.processEvents()
ok(len(aw.asm.components) == 3, "three components are in the assembly")
cols = {tuple(round(float(x), 3) for x in aw.base_color(c, e["k"])) for c, e in ((aw.asm.comp(cid), e) for cid, e in aw.entries.items())}
ok(cols == {tuple(round(float(x), 3) for x in view3d.part_rgb())}, f"every component is the same neutral grey, not a colour each ({cols})")
ok(aw.selector is not None and aw.selector.kind == "general", "the assembly has the selector beside Show")
ok(aw.shadow is not None and aw.shadow.actor is not None, "and the floor shadow under the components")
ok(aw.pick_filter == {"face": True, "edge": True, "vertex": True}, "General: a tool may pick all three kinds")
aw.selector.set_kind("edge", quiet=True)
ok(aw.pick_filter == {"face": False, "edge": True, "vertex": False}, "Edge: a tool picks edges only")
aw.selector.set_kind("general", quiet=True)

c0 = aw.asm.components[0]
e0 = aw.entries[c0["id"]]
M0 = aw.asm.T4(c0)
cc = np.array(e0["mesh"].center)
centre = (M0[:3, :3] @ cc) + M0[:3, 3]
sx, sy = aw.ed.to_screen(np.array([centre]))[0]
# the cursor on a component: with General nothing is outlined
aw.on_hover(int(sx), int(sy))
ok(aw.hover_actor is None, "normal mode, General: nothing is outlined (a click would pick a component)")
aw.selector.set_kind("body", quiet=True)
hit = aw.hover_item(int(sx), int(sy))
ok(hit is not None and hit["kind"] == "body", "Body: the component under the cursor is what would be picked")
aw.on_hover(int(sx), int(sy))
ok(aw.hover_actor is not None, "and it is tinted")
aw.selector.set_kind("face", quiet=True)
aw.on_hover(int(sx), int(sy))
fh = aw.hover_item(int(sx), int(sy))
if fh is not None:
    ok(fh["kind"] == "face" and aw.hover_actor is not None and aw.hover_actor.GetMapper().dataset.GetNumberOfPolys() == 0, "Face: the face under the cursor gets an outline (lines, not a fill)")
else:
    ok(False, "Face: a face is under the cursor")
# a click
aw.on_click(int(sx), int(sy))
ok(len(aw.pick_sel) == 1 and aw.pick_sel[0]["kind"] == "face" and aw.sel_comp is None, "Face: a click picks the face, not the component")
ok(len(aw.hi_actors) >= 1, "and the face is drawn selected")
aw.selector.set_kind("general", quiet=True)
aw.selector_changed("general")
ok(aw.pick_sel == [], "changing the selector lets go of the pick")
aw.on_click(int(sx), int(sy))
ok(aw.sel_comp is not None, "General: a click selects the component, as before")
aw.selector.set_kind("body", quiet=True)
aw.set_mode("mate", quiet=True)
ok(aw.selector.kind == "general", "a mate tool puts Body back to General")
aw.set_mode(None, quiet=True)
# the settings reach the assembly
settings.set_many({"part_color": "#336699"})
aw.settings_changed(["part_color"])
ok(np.allclose(aw.base_color(aw.asm.comp(c0["id"]), 0), settings.rgb("part_color")), "the part colour setting is what a component is drawn in")
settings.set_many({"shadow": False})
aw.settings_changed(["shadow"])
ok(aw.shadow.actor is None, "Shadow off takes the assembly's shadow away")
settings.reset()
aw.settings_changed(["shadow", "part_color"])
ok(aw.shadow.actor is not None, "and back on draws it again")

print("\n" + ("FAILED: " + "; ".join(FAILS) if FAILS else "PASS"))
sys.stdout.flush()
os._exit(1 if FAILS else 0)
