"""Drawings (dev add-on drawings): the surface of the shaded display styles, without a window (dr_shade.py, dr_proj.py, dr_model.py) - the light, the picture of a mesh (area, place, depth,
smooth shading, a banded large triangle, the size limit), the triangles of a real model in every view (the same frame as the lines; the normal of every face the way the light needs it,
a hole too, a cylinder smooth), the mesh as text in the file, and what the document does with it when the style changes.   python test_dr_shade.py"""
import faulthandler
faulthandler.dump_traceback_later(280, exit=True)
import copy
import json
import math
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "drawings"), os.path.join(HERE, "dev_addons", "workbench"), os.path.join(HERE, "shared"), HERE]
import numpy as np
import dr_model as M
import dr_proj as P
import dr_shade as SH
import wb_example as ex

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def near(a, c, tol=1e-6):
    return abs(a - c) <= tol


def mesh(V, T):
    return SH.encode(np.array(V, float), np.array(T))


def pixel(im, x, y):
    """The (grey, alpha) of the picture at the point (x, y) of the view's frame."""
    c, r = int((x - im.x0) * im.px), int((im.y1 - y) * im.px)
    return int(im.rgba[r, c, 0]), int(im.rgba[r, c, 3])


FRONT = (0.0, 0.0, 1.0)
G_FRONT = float(SH.grey(SH.brightness(FRONT)))

# ----------------------------------------------------------------------------------------------------------------------------------- the light
ok(near(float(np.linalg.norm(SH.LIGHT)), 1.0), "the light is a unit direction")
ok(SH.LIGHT[0] < 0 < SH.LIGHT[1] and SH.LIGHT[2] > 0.5, "from the upper left and in front")
ok(near(float(SH.brightness(SH.LIGHT)), 1.0), "a surface that faces the light is as bright as it gets")
ok(near(float(SH.brightness(-SH.LIGHT)), SH.AMBIENT) and near(float(SH.brightness((1.0, 0.0, 0.0))), SH.AMBIENT), "one that faces away, or only sideways from the light, still has the light that is everywhere")
ok(float(SH.brightness(FRONT)) > float(SH.brightness((0.0, 1.0, 0.0))) > float(SH.brightness((-1.0, 0.0, 0.0))) > float(SH.brightness((1.0, 0.0, 0.0))), "the front is brighter than the top, the top brighter than the left, the left brighter than the right")
ok(near(float(SH.grey(0.0)), 70.0) and near(float(SH.grey(1.0)), 245.0) and 200 < G_FRONT < 235, f"a grey between 70 and 245: a surface that faces the viewer is {G_FRONT:.0f}, light enough for black lines to show on it")

# ----------------------------------------------------------------------------------------------------------------------------------- the picture of a mesh
SQ = mesh([[0, 0, 0, 0, 0, 1], [10, 0, 0, 0, 0, 1], [10, 10, 0, 0, 0, 1], [0, 10, 0, 0, 0, 1]], [[0, 1, 2], [0, 2, 3]])
im = SH.render(SQ, 8.0, 2)
cover = float(im.rgba[..., 3].sum()) / 255.0
ok(near(cover, 6400.0, 1.0), f"a square of 10 x 10 mm at 8 pixels to the mm covers 6400 pixels ({cover:.1f})")
ok(near(im.px, 8.0) and im.rgba.dtype == np.uint8 and im.rgba.shape[2] == 4, "the picture is 8 pixels to the mm, 8 bits, grey with an alpha")
g, a = pixel(im, 5.0, 5.0)
ok(a == 255 and abs(g - G_FRONT) <= 0.5, f"in the middle: opaque, the grey of a surface that faces the viewer ({g} against {G_FRONT:.1f})")
ok(pixel(im, 5.0, 5.0)[0] == pixel(im, 9.0, 1.0)[0] == pixel(im, 1.0, 9.0)[0], "flat all over, the diagonal between the two triangles does not show")
ok(pixel(im, -0.1, 5.0)[1] == 0 and pixel(im, 10.1, 5.0)[1] == 0 and pixel(im, 5.0, 10.1)[1] == 0 and pixel(im, 5.0, -0.1)[1] == 0, "just outside, in the pixel that is the margin of the picture: nothing")
ok(pixel(im, 0.0 + 1.0 / 8, 5.0)[1] == 255 and pixel(im, 10.0 - 1.0 / 8, 5.0)[1] == 255, "the edges are where they should be (to a pixel)")
# the place: a point of the view's frame is at the pixel the picture says
L = mesh([[2, 3, 0, 0, 0, 1], [4, 3, 0, 0, 0, 1], [4, 7, 0, 0, 0, 1]], [[0, 1, 2]])
iml = SH.render(L, 10.0, 2)
ok(pixel(iml, 3.8, 3.5)[1] == 255 and pixel(iml, 3.8, 6.0)[1] == 255 and pixel(iml, 2.2, 6.5)[1] == 0 and pixel(iml, 3.0, 6.0)[1] == 0, "a right triangle (2, 3) (4, 3) (4, 7): the lower right is in, the upper left is out, and so is a point above the slanting side")
cov_t = float(iml.rgba[..., 3].sum()) / 255.0
ok(abs(cov_t - 0.5 * 2 * 4 * 100) <= 3.0, f"its area is 4 mm2 = 400 pixels ({cov_t:.1f})")
# anti-aliased edge: half covered pixels
HALF = mesh([[0, 0, 0, 0, 0, 1], [10.5, 0, 0, 0, 0, 1], [10.5, 10, 0, 0, 0, 1], [0, 10, 0, 0, 0, 1]], [[0, 1, 2], [0, 2, 3]])
imh = SH.render(HALF, 1.0, 4)
col = imh.rgba[5, :, 3]
ok(any(0 < int(v) < 255 for v in col) and int(col.max()) == 255, f"an edge that is half way into a pixel gives a half transparent pixel ({sorted(set(int(v) for v in col))})")
ok(abs(float(imh.rgba[..., 3].sum()) / 255.0 - 105.0) <= 1.5, "and the area still adds up (105 pixels)")

# depth: what is nearer is seen, whatever the order of the triangles
near_sq = [[2, 2, 5, 0, 0, 1], [8, 2, 5, 0, 0, 1], [8, 8, 5, 0, 0, 1], [2, 8, 5, 0, 0, 1]]
far_sq = [[0, 0, 1, 0, 1, 0], [10, 0, 1, 0, 1, 0], [10, 10, 1, 0, 1, 0], [0, 10, 1, 0, 1, 0]]
a_ = mesh(far_sq + near_sq, [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
b_ = mesh(far_sq + near_sq, [[4, 5, 6], [4, 6, 7], [0, 1, 2], [0, 2, 3]])
g_near, g_far = float(SH.grey(SH.brightness(FRONT))), float(SH.grey(SH.brightness((0.0, 1.0, 0.0))))
ia, ib = SH.render(a_, 8.0, 2), SH.render(b_, 8.0, 2)
ok(abs(pixel(ia, 5, 5)[0] - g_near) <= 0.5 and abs(pixel(ia, 1, 1)[0] - g_far) <= 0.5, f"a small square in front of a big one: in front where they overlap ({pixel(ia, 5, 5)[0]}), behind outside it ({pixel(ia, 1, 1)[0]})")
ok(np.array_equal(ia.rgba, ib.rgba), "and the same picture whichever is drawn first")
# two triangles that go through each other: the nearer one changes along the line where they meet
X1 = [[0, 0, 0, 0, 0, 1], [10, 0, 0, 0, 0, 1], [5, 10, 10, 0, 0, 1]]                  # rises from z = 0 to z = 10 going up
X2 = [[10, 10, 0, 1, 0, 0], [0, 10, 0, 1, 0, 0], [5, 0, 10, 1, 0, 0]]                 # rises going down: they cross at y = 5, both z = 5
ix = SH.render(mesh(X1 + X2, [[0, 1, 2], [3, 4, 5]]), 10.0, 1)
g1, g2 = float(SH.grey(SH.brightness((0, 0, 1)))), float(SH.grey(SH.brightness((1, 0, 0))))
ok(abs(pixel(ix, 5.0, 8.0)[0] - g1) <= 1 and abs(pixel(ix, 5.0, 2.0)[0] - g2) <= 1, f"triangles that cross: the one that is nearer at each place is seen ({pixel(ix, 5.0, 8.0)[0]} above, {pixel(ix, 5.0, 2.0)[0]} below)")

# smooth shading: the normals are given at the corners
tn = mesh([[0, 0, 0, 0, 0, 1], [10, 0, 0, 1, 0, 0], [0, 10, 0, -1, 0, 0]], [[0, 1, 2]])
it = SH.render(tn, 10.0, 1)
b0, b1, b2 = (float(SH.brightness(n)) for n in ((0, 0, 1), (1, 0, 0), (-1, 0, 0)))
ok(abs(pixel(it, 0.3, 0.3)[0] - float(SH.grey(b0))) <= 8 and abs(pixel(it, 9.0, 0.3)[0] - float(SH.grey(b1))) <= 8 and abs(pixel(it, 0.3, 9.0)[0] - float(SH.grey(b2))) <= 8,
   f"a triangle with different normals at its corners: each corner has its own grey ({pixel(it, 0.3, 0.3)[0]}, {pixel(it, 9.0, 0.3)[0]}, {pixel(it, 0.3, 9.0)[0]})")
cx, cy = 10.0 / 3.0, 10.0 / 3.0
nmid = (np.array([0, 0, 1.0]) + np.array([1.0, 0, 0]) + np.array([-1.0, 0, 0])) / 3.0
nmid = nmid / np.linalg.norm(nmid)
ok(abs(pixel(it, cx, cy)[0] - float(SH.grey(SH.brightness(nmid)))) <= 4, "and in the middle the grey of the mean of the three normals")
# a triangle that faces away and is seen (an open surface) is lit as seen
back = mesh([[0, 0, 0, 0, 0, -1], [0, 10, 0, 0, 0, -1], [10, 0, 0, 0, 0, -1]], [[0, 1, 2]])            # clockwise: faces away; its normals say the same
ib_ = SH.render(back, 8.0, 1)
ok(abs(pixel(ib_, 2.0, 2.0)[0] - G_FRONT) <= 0.5, f"a surface that faces away but is the one that is seen (an open shell) is lit from the side it is seen from ({pixel(ib_, 2.0, 2.0)[0]})")

# a large triangle in bands is the same as in one piece; a degenerate one is nothing
BIG = mesh([[0, 0, 0, 0, 0, 1], [60, 0, 0, 0.3, 0, 0.95], [0, 40, 0, -0.3, 0.2, 0.93]], [[0, 1, 2]])
whole = SH.render(BIG, 12.0, 2)
old = SH.BUDGET
SH.BUDGET = 3000
banded = SH.render(BIG, 12.0, 2)
many = SH.render(mesh(np.vstack([np.array([[0, 0, 0, 0, 0, 1], [60, 0, 0, 0.3, 0, 0.95], [0, 40, 0, -0.3, 0.2, 0.93]]) + [dx, 0, 0, 0, 0, 0] for dx in (0, 70)]), [[0, 1, 2], [3, 4, 5]]), 12.0, 2)
SH.BUDGET = old
ok(np.array_equal(whole.rgba, banded.rgba), f"a triangle of {whole.width} x {whole.height} pixels is drawn the same in one piece and in bands of rows")
ok(abs(float(whole.rgba[..., 3].sum()) / 255.0 - 0.5 * 60 * 40 * 144) <= 0.002 * 0.5 * 60 * 40 * 144, "with its area (to a thousandth)")
ok(many.width > whole.width and abs(float(many.rgba[..., 3].sum()) - 2.0 * float(whole.rgba[..., 3].sum())) <= 0.002 * float(whole.rgba[..., 3].sum()), "two triangles side by side (chunks of several): twice the area")
deg = SH.render(mesh([[0, 0, 0, 0, 0, 1], [5, 5, 0, 0, 0, 1], [10, 10, 0, 0, 0, 1], [0, 0, 1, 0, 0, 1], [4, 0, 1, 0, 0, 1], [0, 4, 1, 0, 0, 1]], [[0, 1, 2], [3, 4, 5]]), 10.0, 1)
area_deg = float(deg.rgba[..., 3].sum()) / 255.0
ok(abs(area_deg - 800.0) <= 24.0 and deg.rgba[..., 3].max() == 255, f"a triangle that is a line on the picture adds nothing; the other one is there (800 pixels: {area_deg:.0f})")
ok(SH.render({"n": 0, "m": 0, "v": "", "t": ""}, 5.0) is None, "no triangles: no picture")
# the size limit
huge = SH.render(mesh([[0, 0, 0, 0, 0, 1], [3000, 0, 0, 0, 0, 1], [0, 2000, 0, 0, 0, 1]], [[0, 1, 2]]), 10.0, 2)
ok(huge is not None and huge.px < 10.0 and huge.width * huge.height <= SH.MAX_SAMPLES, f"a picture that would be too big is made smaller ({huge.px:.2f} pixels to the mm, {huge.width} x {huge.height})")

# the mesh as text
V = np.array([[1.5, -2.25, 3.0, 0.0, 0.6, 0.8], [4.0, 5.0, -6.0, 1.0, 0.0, 0.0], [7.0, 8.0, 9.0, 0.0, 0.0, 1.0]])
mt = SH.encode(V, [[0, 1, 2]])
V2, T2 = SH.decode(mt)
ok(mt["n"] == 3 and mt["m"] == 1 and isinstance(mt["v"], str) and np.allclose(V2, V) and T2.tolist() == [[0, 1, 2]], "a mesh is text (so a copy of the document costs nothing) and comes back as it was")
ok(len(json.dumps(mt)) < 300, f"and small ({len(json.dumps(mt))} bytes for 3 corners)")
for bad in ({"n": 3, "m": 1, "v": "!!", "t": "AAAA"}, {"n": 3}, {"n": 3, "m": 1, "v": mt["v"], "t": SH.encode(V, [[0, 1, 5]])["t"]}, "mesh", None):
    try:
        SH.decode(bad)
        ok(False, f"a damaged mesh is refused: {str(bad)[:40]}")
    except ValueError:
        ok(True, f"a damaged mesh is refused: {str(bad)[:40]}")

# ----------------------------------------------------------------------------------------------------------------------------------- the triangles of a real model
from build123d import Box, Cylinder, Pos
body = Box(100, 60, 10) - Pos(-20, 0, 0) * Cylinder(8, 10)
shape = body + Pos(25, 10, 11) * Cylinder(10, 12)
for name in P.ORIENTATIONS:
    pr = P.project(shape, name, hidden=False, mesh=True)
    b1, b2 = pr.bbox(), SH.bbox(pr.mesh)
    ok(all(near(x, y, 1e-3) for x, y in zip(b1, b2)), f"{name}: the triangles fill the same box as the lines ({tuple(round(v, 2) for v in b2)})")
pr0 = P.project(shape, "Front", hidden=False)
ok(pr0.mesh is None and "mesh" not in pr0.to_json(), "a view that is not shaded has no triangles (and the file does not carry any)")
prm = P.project(shape, "Isometric", hidden=False, mesh=True)
back_ = P.Projection.from_json(json.loads(json.dumps(prm.to_json())))
ok(back_.mesh == prm.mesh and SH.decode(back_.mesh)[0].shape[1] == 6, "the triangles go through the file as they are")
damaged = prm.to_json()
damaged["mesh"] = {"n": 3, "m": 1, "v": "xx", "t": "yy"}
ok(P.Projection.from_json(damaged).mesh is None and len(P.Projection.from_json(damaged).vis) == len(prm.vis), "a damaged mesh in a file is left out: the view shows its lines")

# the grey of every face of a box is the light on its normal, in the axonometric view
bx = Box(40, 30, 20)
for name in ("Isometric", "Trimetric", "Dimetric", "Front", "Top", "Right"):
    eye, up, right = P.view_axes(name)
    R = np.array([right, up, eye])
    pr = P.project(bx, name, hidden=False, mesh=True)
    im = SH.render(pr.mesh, 6.0, 2)
    seen, bad = 0, []
    for n_model, centre in (((0, 0, 1), (0, 0, 10)), ((0, 0, -1), (0, 0, -10)), ((0, -1, 0), (0, -15, 0)), ((0, 1, 0), (0, 15, 0)), ((1, 0, 0), (20, 0, 0)), ((-1, 0, 0), (-20, 0, 0))):
        nv = R @ np.array(n_model, float)
        if nv[2] < 0.2:                                                          # a face that is turned away or edge on
            continue
        cxy = R @ np.array(centre, float)
        g, a = pixel(im, float(cxy[0]), float(cxy[1]))
        want = float(SH.grey(SH.brightness(nv)))
        seen += 1
        if a != 255 or abs(g - want) > 1.0:
            bad.append((n_model, g, round(want, 1)))
    ok(seen >= 1 and not bad, f"{name}: the {seen} faces that can be seen are as light as the light on their normals says {bad if bad else ''}")

# a hole: the wall is lit as a wall of material (its normal points into the hole)
plate = Box(60, 60, 10) - Cylinder(8, 10)
eye, up, right = P.view_axes("Isometric")
R = np.array([right, up, eye])
imh = SH.render(P.project(plate, "Isometric", hidden=False, mesh=True).mesh, 10.0, 2)
phi = math.radians(135.0)                                                         # the side of the hole that the viewer faces
wall = np.array([8.0 * math.cos(phi), 8.0 * math.sin(phi), 4.3])
n_wall = np.array([-math.cos(phi), -math.sin(phi), 0.0])
xy = R @ wall
g, a = pixel(imh, float(xy[0]), float(xy[1]))
want = float(SH.grey(SH.brightness(R @ n_wall)))
wrong = float(SH.grey(SH.brightness(-(R @ n_wall))))
ok(a == 255 and abs(g - want) <= 3.0 and abs(g - wrong) > 8.0, f"the wall of a hole, seen in the isometric view: {g}, as lit as a wall that faces the hole's axis ({want:.0f}), not as one that faces out ({wrong:.0f})")

# a cylinder is smooth: the grey goes across it without a step, the seam of the surface does not show
cyl = Cylinder(10, 30)
for name in ("Front", "Right", "Left", "Back"):
    pr = P.project(cyl, name, hidden=False, mesh=True)
    im = SH.render(pr.mesh, 10.0, 2)
    row = [int(im.rgba[im.rgba.shape[0] // 2, c, 0]) for c in range(2, im.rgba.shape[1] - 2) if im.rgba[im.rgba.shape[0] // 2, c, 3] == 255]
    steps = [abs(row[i + 1] - row[i]) for i in range(len(row) - 1)]
    ok(len(row) > 150 and max(steps) <= 6 and max(row) - min(row) > 40, f"a cylinder in the {name} view: smooth across ({len(row)} pixels, the biggest step {max(steps)}, from {min(row)} to {max(row)})")

# a sphere: the grey at every point is the light on the true normal of a sphere there (the surface's own normals, not the ones of the flat triangles)
from build123d import Sphere
for name in ("Top", "Isometric"):
    im = SH.render(P.project(Sphere(20), name, hidden=False, mesh=True).mesh, 8.0, 2)
    errs = []
    for x in np.linspace(-17.0, 17.0, 15):
        for y in np.linspace(-17.0, 17.0, 15):
            if x * x + y * y > 17.0 ** 2:
                continue
            nrm = np.array([x, y, math.sqrt(400.0 - x * x - y * y)]) / 20.0
            errs.append(abs(pixel(im, float(x), float(y))[0] - float(SH.grey(SH.brightness(nrm)))))
    ok(max(errs) <= 1.5 and len(errs) > 100, f"a sphere in the {name} view: within {max(errs):.1f} grey levels of the true light at {len(errs)} points")

# ----------------------------------------------------------------------------------------------------------------------------------- the document
bar, _sid = ex.part_doc(100, 20, 10)
d = M.Drawing()
mid = d.add_model("Bar", "part", bar, src="n1")
ok([k for k, _l in M.STYLES] == ["wireframe", "hlv", "hlr", "shaded_edges", "shaded"] and M.SHADED == ("shaded_edges", "shaded"), "five display styles: the two shaded ones come last")
v = d.add_view(mid, "Isometric", (100, 100), scale=1.0, style="hlv")
vid = v["id"]
ok(d.projection(d.view(vid)).mesh is None and d.projection(d.view(vid)).hid, "a view with hidden lines visible has its hidden lines and no triangles")
d.set_style(vid, "shaded")
pr = d.projection(d.view(vid))
ok(pr.mesh is not None and not pr.hid and pr.vis, "in a shaded style it has triangles, the visible lines (to dimension, and to draw on Shaded With Edges), no hidden lines")
ok("mesh" in d.view(vid)["geom"] and d.view(vid)["style"] == "shaded", "the triangles are in the view's record")
m_before = d.view(vid)["geom"]["mesh"]
d.set_style(vid, "shaded_edges")
ok(d.view(vid)["geom"]["mesh"] is m_before, "from one shaded style to the other: the same triangles, nothing is made again")
d.set_style(vid, "hlr")
ok("mesh" not in d.view(vid)["geom"] and not d.projection(d.view(vid)).hid, "from a shaded style to Hidden Lines Removed: the triangles go, there are still no hidden lines")
d.set_style(vid, "shaded")
ok(d.projection(d.view(vid)).mesh is not None and not d.projection(d.view(vid)).hid, "and back: the triangles are made again")
d.set_style(vid, "wireframe")
ok("mesh" not in d.view(vid)["geom"] and d.projection(d.view(vid)).hid, "to Wireframe: the hidden lines come back, the triangles are gone")
d.set_style(vid, "shaded_edges")
sn = d.snapshot()
t0 = copy.deepcopy(d.view(vid)["geom"]["mesh"])
d.set_style(vid, "hlv")
d.restore(sn)
ok(d.view(vid)["style"] == "shaded_edges" and d.projection(d.view(vid)).mesh is not None and d.view(vid)["geom"]["mesh"] == t0, "undo brings the triangles back")
ok(sn["views"][0]["geom"]["mesh"]["v"] is d.view(vid)["geom"]["mesh"]["v"], "a copy of the document for undo holds the very same text: it costs nothing")
e = M.Drawing.from_json(d.to_json())
ok(e.view(vid)["style"] == "shaded_edges" and e.projection(e.view(vid)).mesh is not None and SH.decode(e.projection(e.view(vid)).mesh)[1].shape[0] == SH.decode(d.projection(d.view(vid)).mesh)[1].shape[0],
   "the file keeps the style and the triangles: a drawing opens shaded without its models")
sized = len(d.to_json())
d.set_style(vid, "hlv")
ok(len(d.to_json()) < sized and "mesh" not in d.to_json(), f"and a drawing without a shaded view has none ({sized} -> {len(d.to_json())} bytes)")
d.set_style(vid, "shaded")
# projected views
pv = d.add_projected(vid, "right", (170, 100))
ok(pv["style"] in M.STYLE_KEYS and d.projection(pv).vis, "a view projected from a shaded view is made")
d.set_style(pv["id"], "shaded")
ok(d.projection(pv).mesh is not None and d.projection(pv).mesh != d.projection(d.view(vid)).mesh, "it has its own triangles: they look the way it looks")
# a model that changes: the views are projected again and keep their shading
bar2, _ = ex.part_doc(120, 20, 10)
d.set_style(vid, "shaded")
before = d.view(vid)["geom"]["mesh"]
d.refresh_model(mid, bar2)
after = d.view(vid)["geom"]["mesh"]
bb = SH.bbox(after)
ok(after != before and bb[2] - bb[0] > SH.bbox(before)[2] - SH.bbox(before)[0] + 5.0, f"a model that changed: the views are shaded again, from the new model ({SH.bbox(before)[2] - SH.bbox(before)[0]:.1f} -> {bb[2] - bb[0]:.1f} mm wide)")
# a damaged style in the file
text = json.loads(d.to_json())
text["views"][1]["style"] = "sparkly"
ok(len(M.Drawing.from_json(json.dumps(text)).views) == len(d.views) - 1, "a style that is not one: the view is left out, the rest opens")

print("-" * 70)
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED")
sys.exit(1 if FAILS else 0)
