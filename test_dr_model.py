"""Drawings (dev add-on drawings): the document of a drawing (dr_model.py) with real parts and assemblies - the sheet, the copies of the models, a model view placed by its middle, the
sheet scale that fits the first view, projected views (third- and first-angle) that stay aligned with their parent, moving (a projected view only along its axis, its children with it),
scales typed or from the list, display styles, removing views and models, refreshing a model, and the file (a drawing shows without its models).   python test_dr_model.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import json
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
import numpy as np
import dr_geom
import dr_model as M
import dr_sheet as S
import wb_example as ex

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


bar, _sid = ex.part_doc(100, 20, 10)                       # a bar 100 x 20 (sketch on Top) x 10 high: X 100, Y 20, Z 10
long_bar, _s2 = ex.part_doc(150, 20, 10)
frame = ex.frame_asm(100, 20, 20)

d = M.Drawing()
ok(d.sheet == {"size": "ansi_a", "landscape": True, "first_angle": False} and d.sheet_dims() == (11 * 25.4, 8.5 * 25.4), "a new drawing: Letter landscape, third-angle projection")
ok(d.models == [] and d.views == [], "with no model and no view")
d.set_sheet("iso_a3", False)
ok(d.sheet_dims() == (297.0, 420.0), "A3 portrait is 297 x 420 mm")
try:
    d.set_sheet("custom")
    ok(False, "a custom size is refused")
except M.DrawingError as ex_:
    ok("standard" in str(ex_), f"no custom sheet size ({ex_})")
d.set_sheet("ansi_a", True)

# ---- the models
m1 = d.add_model("Bar", "part", bar, src="n1")
m2 = d.add_model("Frame", "assembly", frame, src="n2")
ok([m["id"] for m in d.models] == ["m1", "m2"] and d.model(m1)["kind"] == "part" and d.model_of_src("n2")["id"] == m2, "a part and an assembly are copied in, and remember the block they came from")
ok(d.model(m1)["hash"] != d.model(m2)["hash"] and len(d.model(m1)["hash"]) == 40, "each has a fingerprint")
try:
    d.add_model("x", "sketch", {})
    ok(False, "only parts and assemblies")
except M.DrawingError:
    ok(True, "only a part or an assembly can be shown")
sh = d.shape(m1)
ok(near(sh.bounding_box().size.X, 100) and near(sh.bounding_box().size.Z, 10), "the shape of the part is built from its copy")
ok(d.shape(m1) is sh, "and made once")

# ---- the first view: placed by its middle, and the scale that fits
v1 = d.add_view(m1, "Front", (100.0, 120.0))
x0, y0, x1, y1 = d.bbox(v1)
ok(near((x0 + x1) / 2, 100.0) and near((y0 + y1) / 2, 120.0), f"a model view is put with the middle of its lines where it was clicked ({(x0 + x1) / 2:.2f}, {(y0 + y1) / 2:.2f})")
ok(v1["scale"] == 1.0 and d.scale == 1.0 and near(x1 - x0, 100.0) and near(y1 - y0, 10.0), "a 100 x 10 bar fits Letter at 1:1")
ok(v1["name"] == "Drawing View1" and v1["style"] == "hlv" and v1["kind"] == "model" and v1["parent"] is None, "named Drawing View1, hidden lines visible")
big, _s = ex.part_doc(1000, 200, 100)
d2 = M.Drawing()
mb = d2.add_model("Big", "part", big)
vb = d2.add_view(mb, "Front", (140.0, 100.0))
ok(vb["scale"] == 0.1 and d2.scale == 0.1 and M.scale_text(vb["scale"]) == "1:10", f"a 1000 mm part: the first view sets the sheet scale so it fits (1:10, got {M.scale_text(vb['scale'])})")
small, _s = ex.part_doc(10, 5, 5)
d3 = M.Drawing()
vs = d3.add_view(d3.add_model("Small", "part", small), "Front", (100, 100))
ok(vs["scale"] == 10.0 and M.scale_text(vs["scale"]) == "10:1", f"a 10 mm part is drawn at 10:1 ({M.scale_text(vs['scale'])})")
v1b = d.add_view(m1, "Top", (100.0, 60.0))
ok(v1b["scale"] == d.scale and v1b["name"] == "Drawing View2", "a later model view starts at the sheet scale")
d.remove_view(v1b["id"])

# ---- projected views
vr = d.add_projected(v1["id"], "right", (200.0, 90.0))
ok(vr["kind"] == "projected" and vr["parent"] == v1["id"] and vr["side"] == "right" and vr["scale"] == v1["scale"], "a projected view has its parent and its side, and the scale of its parent")
ok(near(vr["origin"][1], v1["origin"][1]), "to the right: it has the height of its parent (the origin of the model is at the same height: aligned)")
rx0, ry0, rx1, ry1 = d.bbox(vr)
ok(near((rx0 + rx1) / 2, 200.0), f"and is put by the middle of its lines where it was clicked ({(rx0 + rx1) / 2:.2f})")
ok(near(rx1 - rx0, 20.0) and near(ry1 - ry0, 10.0), "its size is that of the Right view of the bar: 20 x 10")
ok(np.allclose(vr["eye"], (1, 0, 0)) and np.allclose(vr["up"], (0, 0, 1)), "third-angle: the view on the right shows the right side (eye on +X, Z up)")
vt = d.add_projected(v1["id"], "up", (100.0, 170.0))
ok(near(vt["origin"][0], v1["origin"][0]) and np.allclose(vt["eye"], (0, 0, 1)) and np.allclose(vt["up"], (0, 1, 0)), "above: the Top view (eye +Z, the back at the top), in line with its parent")
tx0, ty0, tx1, ty1 = d.bbox(vt)
ok(near(tx1 - tx0, 100.0) and near(ty1 - ty0, 20.0), "100 x 20: the plan of the bar")
vd = d.add_projected(v1["id"], "down", (100.0, 60.0))
vl = d.add_projected(v1["id"], "left", (20.0, 120.0))
ok(np.allclose(vd["eye"], (0, 0, -1)) and np.allclose(vd["up"], (0, -1, 0)) and np.allclose(vl["eye"], (-1, 0, 0)), "below the Bottom view (front at its top), on the left the Left view")
vv = d.add_projected(vr["id"], "up", (200.0, 160.0))
ok(near(vv["origin"][0], vr["origin"][0]) and vv["parent"] == vr["id"] and np.allclose(vv["eye"], (0, 0, 1)), "a view can be projected from a projected view (above the Right view: the Top view again)")
ok([c["id"] for c in d.children(v1["id"])] == [vr["id"], vt["id"], vd["id"], vl["id"]] and {c["id"] for c in d.descendants(v1["id"])} == {vr["id"], vt["id"], vd["id"], vl["id"], vv["id"]}, "children and descendants")
for pos, want in (((150, 120), "right"), ((50, 120), "left"), ((100, 150), "up"), ((100, 90), "down")):
    ok(d.side_of(v1["id"], pos) == want, f"a click at {pos} is on the {want} of the parent")
try:
    d.add_projected(v1["id"], "diagonal", (0, 0))
    ok(False, "a side must be one of four")
except M.DrawingError:
    ok(True, "a projected view goes to the right, left, up or down only")

# ---- first-angle projection: the other side
before = np.array(vr["eye"])
d.set_sheet(first_angle=True)
ok(np.allclose(vr["eye"], (-1, 0, 0)) and np.allclose(vt["eye"], (0, 0, -1)), "first-angle: the view on the right shows the LEFT side, the view above shows the bottom")
ok(near(vr["origin"][1], v1["origin"][1]), "and stays where it is, aligned")
d.set_sheet(first_angle=False)
ok(np.allclose(vr["eye"], before), "back to third-angle")

# ---- moving: a projected view only along its axis, with its children
ox, oy = vr["origin"]
tox, toy = vv["origin"]
dx, dy = d.shift_view(vr["id"], 30.0, 25.0)
ok(near(dx, 30.0) and near(dy, 0.0) and near(vr["origin"][1], oy) and near(vr["origin"][0], ox + 30.0), f"a view on the right slides sideways only: the 25 up was ignored ({dx}, {dy})")
ok(near(vv["origin"][0], tox + 30.0) and near(vv["origin"][1], toy), "and the view projected from it went with it")
oxt, oyt = vt["origin"]
d.shift_view(vt["id"], 40.0, 15.0)
ok(near(vt["origin"][0], oxt) and near(vt["origin"][1], oyt + 15.0), "a view above slides up and down only")
p1, p2 = list(v1["origin"]), list(vr["origin"])
dx, dy = d.shift_view(v1["id"], -10.0, 12.0)
ok(near(dx, -10.0) and near(dy, 12.0) and np.allclose(v1["origin"], (p1[0] - 10, p1[1] + 12)), "a model view moves where it is put")
ok(np.allclose(vr["origin"], (p2[0] - 10, p2[1] + 12)) and near(vr["origin"][1], v1["origin"][1]) and near(vt["origin"][0], v1["origin"][0]), "and its projected views move with it, still aligned")

# ---- scale
ok(M.parse_scale("1:2") == 0.5 and M.parse_scale("2:1") == 2.0 and M.parse_scale(" 1 : 4 ") == 0.25 and M.parse_scale("0.5") == 0.5 and M.parse_scale("1/8") == 0.125, "scales are typed like 1:2, 2:1, 0.5 or 1/8")
for bad in ("0", "-1", "abc", "1:0", "", "1:a"):
    try:
        M.parse_scale(bad)
        ok(False, f"'{bad}' is not a scale")
    except M.DrawingError:
        ok(True, f"'{bad}' is refused as a scale")
ok([M.scale_text(v) for v in (1.0, 0.5, 2.0, 0.4, 3.0, 0.25)] == ["1:1", "1:2", "2:1", "1:2.5", "3:1", "1:4"], "and written back the same way")
cx0, cy0, cx1, cy1 = d.bbox(v1)
mid = ((cx0 + cx1) / 2, (cy0 + cy1) / 2)
d.set_scale(v1["id"], "2:1")
nx0, ny0, nx1, ny1 = d.bbox(v1)
ok(near(nx1 - nx0, 200.0) and near(ny1 - ny0, 20.0) and near((nx0 + nx1) / 2, mid[0]) and near((ny0 + ny1) / 2, mid[1]), "2:1 makes the view twice as large around the same middle")
ok(vr["scale"] == 1.0, "(a projected view keeps its own scale until it is changed)")
ok(near(vr["origin"][1], v1["origin"][1]) if vr["side"] in ("right", "left") else near(vr["origin"][0], v1["origin"][0]), "and it stays in line with its parent after the parent's scale changed")
d.set_scale(vr["id"], "1:2")
ok(near(vr["origin"][1], v1["origin"][1]) if vr["side"] in ("right", "left") else near(vr["origin"][0], v1["origin"][0]), "and a projected view with a scale of its own stays in line with its parent")
d.set_scale(vr["id"], 1.0)
d.set_scale(v1["id"], 1.0)
ok(near(d.bbox(v1)[2] - d.bbox(v1)[0], 100.0), "and back")
# a dimension shows the model's size whatever the scale: the lines are the model's, the scale only places them
pr = d.projection(v1)
ok(near(pr.bbox()[2] - pr.bbox()[0], 100.0), "the projection keeps the model's own size (a dimension reads this, not the size on the sheet)")

# ---- display styles
n_hlv = len(d.projection(vr)["hid"] if isinstance(d.projection(vr), dict) else d.projection(vr).hid)
ok(len(d.projection(vr).hid) == 0, "the bar has no hidden lines to show")
holed, _s = ex.part_doc(60, 20, 10)
dh = M.Drawing()
mh = dh.add_model("Plate", "part", holed)
vh = dh.add_view(mh, "Front", (100, 100))
dh.set_style(vh["id"], "hlr")
ok(vh["style"] == "hlr" and len(dh.projection(vh).hid) == 0, "Hidden Lines Removed keeps the visible lines only")
dh.set_style(vh["id"], "wireframe")
dh.set_style(vh["id"], "hlv")
ok(vh["style"] == "hlv", "styles can be changed back")
try:
    dh.set_style(vh["id"], "cartoon")
    ok(False, "unknown style")
except M.DrawingError:
    ok(True, "an unknown style is refused")
ok([k for k, _l in M.STYLES] == ["wireframe", "hlv", "hlr"], "the styles so far: wireframe, hidden lines visible, hidden lines removed (the shaded ones come last)")

# ---- orientation of a model view; the children follow
d.set_orient(v1["id"], "Top")
ok(v1["orient"] == "Top" and np.allclose(v1["eye"], (0, 0, 1)) and np.allclose(vr["eye"], (1, 0, 0)) and np.allclose(vr["up"], (0, 1, 0)) and np.allclose(vt["eye"], (0, 1, 0)) and np.allclose(vt["up"], (0, 0, -1)),
   "a new orientation of the parent turns the views projected from it (folded out of the Top view: the view to its right looks from +X with the back up, the view above looks from the back)")
try:
    d.set_orient(vr["id"], "Top")
    ok(False, "a projected view cannot be re-oriented")
except M.DrawingError:
    ok(True, "a projected view looks along its parent: only the parent's orientation can be changed")
d.set_orient(v1["id"], "Front")

# ---- a second model, an assembly
va = d.add_view(m2, "Isometric", (200.0, 60.0))
ok(len(d.projection(va).vis) >= 9 and va["model"] == m2, "an assembly can be drawn too")

# ---- refresh: the model changed
w0 = d.bbox(v1)
ids = d.refresh_model(m1, long_bar, name="Long bar")
ok(set(ids) == {v1["id"], vr["id"], vt["id"], vd["id"], vl["id"], vv["id"]}, "the views of a model are made again when it changes (and only those)")
w1 = d.bbox(v1)
ok(near(w1[2] - w1[0], 150.0) and d.model(m1)["name"] == "Long bar" and d.model(m1)["hash"] == M.model_hash(long_bar), "the front view of the longer bar is 150 wide now")
ok(near(d.bbox(vt)[2] - d.bbox(vt)[0], 150.0), "and so is the view projected from it")

# ---- removing
n_views = len(d.views)
d.remove_view(vr["id"])
ok(len(d.views) == n_views - 2 and all(v["id"] not in (vr["id"], vv["id"]) for v in d.views), "removing a view removes the views projected from it")
d.remove_model(m1)
ok([v["id"] for v in d.views] == [va["id"]] and [m["id"] for m in d.models] == [m2], "removing a model removes its views")

# ---- the file
d.add_view(m2, "Front", (60.0, 60.0))
text = d.to_json()
j = json.loads(text)
ok(j["format"] == "openpara-drawing" and j["sheet"]["size"] == "ansi_a" and len(j["views"]) == 2 and len(j["models"]) == 1, "the file is JSON with the sheet, the models and the views")
orig = dr_geom.shape_of


def nope(*a, **k):
    raise AssertionError("the model was built")


dr_geom.shape_of = nope
try:
    e = M.Drawing.from_json(text)
    b0 = e.bbox(e.views[0])
    ok(len(e.views) == 2 and near(b0[2] - b0[0], d.bbox(d.views[0])[2] - d.bbox(d.views[0])[0]) and e.models[0]["name"] == "Frame", "a drawing opens and shows its views without building its models")
    ok(e.views[0]["origin"] == d.views[0]["origin"] and e.views[1]["scale"] == d.views[1]["scale"] and e.scale == d.scale and e.counter == d.counter, "with their places and scales")
finally:
    dr_geom.shape_of = orig
e = M.Drawing.from_json(text)
e.set_style(e.views[1]["id"], "hlr")
ok(len(e.projection(e.views[1]).hid) == 0, "and when a view has to be made again the model is built then")
nv = e.add_view(e.models[0]["id"], "Top", (10, 10))
ok(nv["id"] == "v6" or nv["id"] not in [v["id"] for v in e.views[:-1]], f"new views go on numbering where the file stopped ({nv['id']}, {nv['name']})")
for bad in ("not json", json.dumps({"format": "something"}), json.dumps({"format": "openpara-drawing", "version": 99})):
    try:
        M.Drawing.from_json(bad)
        ok(False, "a bad file is refused")
    except M.DrawingError as ex_:
        ok(True, f"a file that is not a drawing is refused ({str(ex_)[:50]})")
print()
if FAILS:
    print(f"FAILURES: {len(FAILS)}")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("ALL OK")
