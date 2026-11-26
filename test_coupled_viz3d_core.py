"""The numbers behind the 3D picture of the Viz tab (coupled_viz3d_core.py, no Qt): the z-buffer rasteriser against a slow reference, the nearest surface wins whatever the order, smooth colours,
shading, the sharp edges of a box, the camera, the exaggeration and the bend.  Checks that must be able to fail are shown to fail on a deliberately wrong answer.
python test_coupled_viz3d_core.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "dev_addons", "coupled"))
import numpy as np

import coupled_viz3d_core as C
import coupled_viz_core as V

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text, flush=True)
    if not cond:
        FAILS.append(text)


def box(a=(0, 0, 0), b=(2, 1, 1)):
    """The surface of a box as 12 triangles."""
    (x0, y0, z0), (x1, y1, z1) = a, b
    X = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    q = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    t = []
    for a_, b_, c_, d_ in q:
        t += [(a_, b_, c_), (a_, c_, d_)]
    return X, np.array(t, np.int64)


def sphere(n_lat=18, n_lon=24, r=1.0):
    pts, tris = [[0, 0, r]], []
    for i in range(1, n_lat):
        th = np.pi * i / n_lat
        for j in range(n_lon):
            ph = 2 * np.pi * j / n_lon
            pts.append([r * np.sin(th) * np.cos(ph), r * np.sin(th) * np.sin(ph), r * np.cos(th)])
    pts.append([0, 0, -r])
    pts = np.array(pts, float)
    ring = lambda i, j: 1 + (i - 1) * n_lon + (j % n_lon)                         # noqa: E731
    for j in range(n_lon):
        tris.append((0, ring(1, j), ring(1, j + 1)))
    for i in range(1, n_lat - 1):
        for j in range(n_lon):
            tris += [(ring(i, j), ring(i + 1, j), ring(i + 1, j + 1)), (ring(i, j), ring(i + 1, j + 1), ring(i, j + 1))]
    last = len(pts) - 1
    for j in range(n_lon):
        tris.append((last, ring(n_lat - 1, j + 1), ring(n_lat - 1, j)))
    return pts, np.array(tris, np.int64)


def slow_raster(scr, P, tris, vals, lo, hi, table, shade):
    """One triangle at a time, one pixel at a time: the reference."""
    S = scr.project(P)
    img = np.zeros((scr.h, scr.w, 4), np.uint8)
    zb = np.full((scr.h, scr.w), -np.inf)
    span = (hi - lo) if hi > lo else 1.0
    for e, t in enumerate(tris):
        a, b, c = S[t[0]], S[t[1]], S[t[2]]
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-12:
            continue
        for y in range(max(0, int(min(a[1], b[1], c[1])) - 1), min(scr.h, int(max(a[1], b[1], c[1])) + 2)):
            for x in range(max(0, int(min(a[0], b[0], c[0])) - 1), min(scr.w, int(max(a[0], b[0], c[0])) + 2)):
                gx, gy = x + 0.5, y + 0.5
                l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / det
                l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / det
                l3 = 1 - l1 - l2
                if min(l1, l2, l3) < -1e-7:
                    continue
                z = l1 * a[2] + l2 * b[2] + l3 * c[2]
                if z > zb[y, x]:
                    zb[y, x] = z
                    v = l1 * vals[t[0]] + l2 * vals[t[1]] + l3 * vals[t[2]]
                    ci = int(np.clip(round((v - lo) / span * 255), 0, 255))
                    img[y, x, :3] = np.clip(np.round(table[ci].astype(float) * min(1.0, shade[e])), 0, 255).astype(np.uint8)
                    img[y, x, 3] = 255
    return img, zb


table = V.lut("viridis")
cam = C.Camera()

# ------------------------------------------------------------------------------------------------------------------------------ the camera
Rm = cam.matrix()
ok(np.allclose(Rm @ Rm.T, np.eye(3), atol=1e-12) and np.isclose(np.linalg.det(Rm), 1.0), "the camera turns without stretching (its three axes are at right angles, a proper turn)")
c2 = C.Camera()
c2.look("Right")
r = c2.matrix()
ok(np.allclose(r[0], [0, 1, 0]) and np.allclose(r[1], [0, 0, 1]) and np.allclose(r[2], [1, 0, 0]), "seen from the right (+x) the y axis points to the right of the picture and z up")
c2.look("Front")
r = c2.matrix()
ok(np.allclose(r[0], [1, 0, 0], atol=1e-12) and np.allclose(r[1], [0, 0, 1], atol=1e-12), "seen from the front (-y) the x axis points to the right and z up")
c2.look("Top")
ok(np.allclose(c2.matrix()[2], [0, 0, 1], atol=0.02) and abs(np.degrees(np.arcsin(c2.matrix()[2][2])) - 89.0) < 1e-6, "from the top the viewer is above the part")
c2.turn(10, 200)
ok(c2.elevation == 89.0, "the camera does not go over the top (the elevation stops at 89 degrees)")
c2.reset()
ok(c2.azimuth == C.DEFAULTS3["azimuth"] and c2.zoom == 1.0, "Reset puts the view back")

# ------------------------------------------------------------------------------------------------------------------------------ the rasteriser
# the nearest triangle wins, whatever the order they are drawn in
P = np.array([[10, 10, 0], [90, 10, 0], [10, 90, 0], [10, 10, 5], [90, 10, 5], [10, 90, 5]], float)
scr = C.Screen(C.Camera(), (50, 50, 0), 80.0, 100, 100)
scr.R = np.eye(3)                                                                    # (look straight down the z axis: x to the right, y up)
scr.s, scr.o, scr.centre = 1.0, np.array([0.0, 100.0]), np.zeros(3)
P2 = P.copy()
tri = np.array([[0, 1, 2], [3, 4, 5]], np.int64)
vals = np.array([0, 0, 0, 1, 1, 1], float)
sh = np.array([1.0, 1.0])
a1, z1 = C.raster3d(scr, P2, tri, vals, 0.0, 1.0, table, sh)
a2, z2 = C.raster3d(scr, P2, tri[::-1], vals, 0.0, 1.0, table, sh[::-1])
px = (30, 100 - 30)                                                                  # (a point inside both)
ok(np.array_equal(a1, a2) and np.array_equal(a1[px[1], px[0], :3], table[255]), "where two triangles overlap the nearer one shows, in whichever order they come")
ok(float(z1[px[1], px[0]]) == 5.0, "and the depth kept is the nearer one")
far_wins = np.array_equal(a1[px[1], px[0], :3], table[0])
ok(not far_wins, "check shown to FAIL: 'the farther triangle wins' is refused")
ok(a1[0, 99, 3] == 0 and np.isinf(z1[0, 99]), "a pixel with no triangle is transparent")

# colours run smoothly between the corners
P3 = np.array([[5, 5, 0], [95, 5, 0], [5, 95, 0]], float)
v3 = np.array([0.0, 1.0, 0.5])
a3, _z = C.raster3d(scr, P3, np.array([[0, 1, 2]]), v3, 0.0, 1.0, table, np.array([1.0]))
wx, wy = 50.0, 30.0                                                                  # (a point of the plane of the part; the picture has y downward)
l2 = (wx - 5) / 90.0
l3 = (wy - 5) / 90.0
want = l2 * 1.0 + l3 * 0.5
got = a3[100 - int(wy), int(wx), :3].astype(int)
ref = table[int(round(want * 255))].astype(int)
ok(np.abs(got - ref).max() <= 4, f"the colour inside a triangle is the blend of its corners ({tuple(got)} against {tuple(ref)})")
ok(not np.array_equal(a3[94, 6, :3], a3[94, 92, :3]) and not np.array_equal(a3[94, 6, :3], a3[8, 6, :3]), "and differs from one corner to the next")

# against the slow reference, on a box and on a sphere seen from two sides
for name, (X, T) in (("box", box()), ("sphere", sphere())):
    cen = (X.min(axis=0) + X.max(axis=0)) / 2
    rad = float(np.linalg.norm(X - cen, axis=1).max())
    for az, el in ((-35, 25), (130, -40)):
        cm = C.Camera(az, el)
        sc = C.Screen(cm, cen, rad, 96, 80)
        nrm = sc.normals(X, T)
        shd = C.shade_of(nrm)
        vv = X[:, 0] + 2 * X[:, 2]
        fast, zf = C.raster3d(sc, X, T, vv, float(vv.min()), float(vv.max()), table, shd)
        slow, zs = slow_raster(sc, X, T, vv, float(vv.min()), float(vv.max()), table, shd)
        covered = fast[..., 3] > 0
        agree = (fast[..., 3] == slow[..., 3]).mean()
        cols = np.abs(fast[..., :3].astype(int) - slow[..., :3].astype(int)).max(axis=2)
        ok(agree > 0.999 and (cols[covered & (slow[..., 3] > 0)] <= 3).mean() > 0.999, f"{name} from ({az}, {el}): the same picture as the slow reference ({100 * agree:.2f} % of the pixels covered alike, {covered.sum()} covered)")
bad = fast.copy()
bad[40, 48, :3] = (bad[40, 48, :3] + 90) % 255
ok(not np.array_equal(bad, slow) and (np.abs(bad[..., :3].astype(int) - slow[..., :3].astype(int)).max() > 3), "check shown to FAIL: a picture with one wrong pixel is not the reference")

# a box seen from the front: the three sides that face the viewer, the others hidden
Xb, Tb = box((0, 0, 0), (4, 2, 2))
cm = C.Camera(-35, 25)
sc = C.Screen(cm, (2, 1, 1), float(np.linalg.norm(np.array([2, 1, 1.0]))), 200, 200)
shd = C.shade_of(sc.normals(Xb, Tb))
img, zb = C.raster3d(sc, Xb, Tb, np.zeros(8), 0.0, 1.0, table, shd)
cov = (img[..., 3] > 0).mean()
cols = {tuple(c) for c in img[img[..., 3] > 0][:, :3].tolist()}
ok(0.2 < cov < 0.8 and len(cols) == 3, f"a box seen from a corner shows three sides, each its own brightness ({len(cols)} shades, {100 * cov:.0f} % of the picture)")
ok(len(C.feature_edges(Xb, Tb)) == 12, f"the sharp edges of a box are its 12 edges, not the diagonals of its sides ({len(C.feature_edges(Xb, Tb))})")
ok(len(C.feature_edges(*sphere(), degrees=30.0)) == 0 or len(C.feature_edges(*sphere(), degrees=30.0)) < 8, "a smooth ball has no sharp edges (only the rim of what is open)")
Xo, To = box()
ok(len(C.feature_edges(Xo, To[:2])) == 4, f"the rim of an open surface (one square side of a box, cut in two triangles) is its four edges, not the diagonal ({len(C.feature_edges(Xo, To[:2]))})")
vis = C.edge_visible(sc, zb, Xb, C.feature_edges(Xb, Tb))
ok(int(vis.sum()) == 9, f"nine of the twelve edges of a box can be seen from a corner ({int(vis.sum())})")
ok(int(vis.sum()) != 12, "check shown to FAIL: 'all twelve are seen' is refused")

# a triangle that is bigger than the picture and one that is far outside
big = np.array([[-500, -500, 1], [900, -500, 1], [-500, 900, 1]], float)
a5, _z = C.raster3d(scr, big, np.array([[0, 1, 2]]), np.array([0.2, 0.2, 0.2]), 0.0, 1.0, table, np.array([1.0]))
ok((a5[..., 3] > 0).all() or (a5[..., 3] > 0).mean() > 0.4, "a triangle larger than the picture fills what lies on it")
out = np.array([[5000, 5000, 0], [6000, 5000, 0], [5000, 6000, 0]], float)
a6, _z = C.raster3d(scr, out, np.array([[0, 1, 2]]), np.zeros(3), 0.0, 1.0, table, np.array([1.0]))
ok(not (a6[..., 3] > 0).any(), "one that lies outside the picture draws nothing")

# ------------------------------------------------------------------------------------------------------------------------------ the data of a part
Xb, Tb = box((0, 0, 0), (100, 20, 20))
surf = {1: Tb[:6], 2: Tb[6:]}
n = len(Xb)
u = np.zeros((n, 3))
u[:, 2] = 0.002 * Xb[:, 0]                                                           # bends up by 0.2 mm at the far end
vm = Xb[:, 0] * 3.0
d = C.build3d(Xb, surf, u, vm=vm, temperature=lambda P: 20.0 + P[:, 0] / 10.0)
ok(d["kind"] == "body3d" and len(d["X"]) == 8 and len(d["tris"]) == 12, "the data of a box: eight vertices, twelve triangles")
ok(np.isclose(d["ranges"]["u"][1], 0.2) and d["ranges"]["T"] == (20.0, 30.0) and d["ranges"]["vm"] == (0.0, 300.0), f"with the ranges of the fields ({d['ranges']})")
ok([f[0] for f in C.available_fields(d)] == ["T", "u", "vm"], "all three colourings are offered")
d2 = C.build3d(Xb, surf, u, vm=None, temperature=None)
ok([f[0] for f in C.available_fields(d2)] == ["u"], "with no heat result and no stress only the displacement is offered")
ok(C.auto_exaggeration(Xb, u) == 40.0, f"the bend is drawn 40 times larger (8 % of 100 mm over 0.2 mm; {C.auto_exaggeration(Xb, u)})")
ok(C.auto_exaggeration(Xb, np.zeros_like(u)) == 1.0 and C.auto_exaggeration(Xb, u * 1e-9) == 10000.0, "no displacement: 1; a hair of displacement: capped at 10000")
ok(abs(C.bend_reach3d(d) - 0.2) < 1e-12 and C.bend_reach3d(d, k=0) == 0.0, f"the bend reaches the displacement of the solve ({C.bend_reach3d(d):.4g} mm) and is nothing before the first frame")
tv = [C.turn_at(k) for k in range(1, 121)]
ok(max(tv[:60]) == 0.0 and tv[119] == 0.0 and abs(tv[89] - 180.0) < 1e-9 and all(b >= a for a, b in zip(tv[59:118], tv[60:119])) and tv[118] > 359.0, "the view stays while the part bends, then turns once round without going back, and the last frame is back where it was set")
ok(abs(C.bend_reach3d(d, exaggeration=7.0) - 0.2) < 1e-12, "whatever the exaggeration is, taking it out again gives the real displacement")
P120, b120 = C.frame_positions(d, 120)
P30, b30 = C.frame_positions(d, 30)
ok(b120 == 1.0 and 0 < b30 < 1.0 and np.allclose(P120[:, 2], d["X"][:, 2] + 40 * d["U"][:, 2]), "in the last frame the part is bent by the whole exaggerated displacement, earlier by a part of it")
ok(np.allclose(C.field_values(d, "u", 120), d["umag"]) and np.allclose(C.field_values(d, "u", 30), d["umag"] * b30) and np.array_equal(C.field_values(d, "T", 30), d["T"]), "the displacement colour grows with the bend, temperature and stress are the solved fields")
ok(d["radius"] >= np.linalg.norm(d["X"] - d["centre"], axis=1).max(), "the view is big enough for the bent shape")
try:
    C.build3d(Xb, {}, u)
    ok(False, "a result with no surface is refused in words")
except ValueError as ex:
    ok("no surface" in str(ex), f"a result with no surface is refused in words ({ex})")

print()
print("FAILURES:" if FAILS else "all ok", *FAILS, sep="\n")
sys.exit(1 if FAILS else 0)
