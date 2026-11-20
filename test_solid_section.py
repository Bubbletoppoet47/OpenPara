"""The cross-section of a solid cut by a plane: area, centroid and second moments of area (solid_section.py, no screen).
Every number is compared with a textbook formula or with an independent polygon integral.   python test_solid_section.py"""
import faulthandler; faulthandler.dump_traceback_later(300, exit=True)
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from build123d import Box, Cone, Cylinder, Compound, Plane, Polygon, Pos, Rot, Sphere, extrude, Face, Wire
import solid_section as sp


def ok(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    assert c, m


def close(a, b, rel=1e-6, absol=1e-7):
    return abs(a - b) <= max(rel * max(abs(a), abs(b)), absol)


def section(solid, plane, face=None):
    faces, warn = sp.cut(solid, plane, face)
    return sp.properties(faces, plane), warn


def poly_props(pts):
    """Area, centroid and the second moments about the centroid of a polygon (Green's theorem), independent of OCC."""
    P = np.asarray(pts, float)
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    A = cr.sum() / 2
    cx = ((x + x1) * cr).sum() / (6 * A)
    cy = ((y + y1) * cr).sum() / (6 * A)
    Ixx = ((y * y + y * y1 + y1 * y1) * cr).sum() / 12
    Iyy = ((x * x + x * x1 + x1 * x1) * cr).sum() / 12
    Ixy = ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * cr).sum() / 24
    sgn = 1 if A > 0 else -1
    A, Ixx, Iyy, Ixy = A * sgn, Ixx * sgn, Iyy * sgn, Ixy * sgn
    return A, cx, cy, Ixx - A * cy * cy, Iyy - A * cx * cx, Ixy - A * cx * cy


# ------------------------------------------------------------------------------------------------------- a rectangle, on the three base planes
blk = Box(20, 40, 60)                                       # x 20, y 40, z 60, centred on the origin
p, w = section(blk, Plane.XY.offset(5))
ok(close(p["area"], 800) and close(p["Ix"], 20 * 40 ** 3 / 12) and close(p["Iy"], 40 * 20 ** 3 / 12) and abs(p["Ixy"]) < 1e-6, "Top plane: a 20 x 40 rectangle, A = 800, Ix = b h^3 / 12, Iy = h b^3 / 12, Ixy = 0")
ok(np.allclose(p["c3"], (0, 0, 5)) and abs(p["c"][0]) < 1e-9 and abs(p["c"][1]) < 1e-9, "its centroid: the middle of the rectangle, at the offset")
ok(close(p["J"], p["Ix"] + p["Iy"]) and close(p["I1"], p["Ix"]) and close(p["I2"], p["Iy"]) and abs(p["theta"]) < 1e-6, "J = Ix + Iy; principal moments are Ix (about the X axis, theta = 0) and Iy")
ok(close(p["rx"], math.sqrt(p["Ix"] / 800)) and close(p["ry"], math.sqrt(p["Iy"] / 800)), "radii of gyration")
ok(all(close(p["ext"][k], d) for k, d in (("+X", 10), ("-X", 10), ("+Y", 20), ("-Y", 20))), "distances to the extreme fibres 10 / 20")
ok(close(p["S"]["+Y"], p["Ix"] / 20) and close(p["S"]["-X"], p["Iy"] / 10), "section moduli I / c (Sx = 5333.3, Sy = 2666.7)")
ok(p["frame"]["names"] == ("+X", "+Y", "+Z") and not w and p["pieces"] == 1, "axes X = model +X, Y = model +Y, normal +Z; no warning; one piece")

p, _ = section(blk, Plane.XZ)
ok(p["frame"]["names"] == ("+X", "+Z", "-Y") and close(p["area"], 20 * 60) and close(p["Ix"], 20 * 60 ** 3 / 12) and close(p["Iy"], 60 * 20 ** 3 / 12), "Front plane: section X = model X, Y = model Z, a 20 x 60 rectangle")
p, _ = section(blk, Plane.YZ)
ok(p["frame"]["names"] == ("+Y", "+Z", "+X") and close(p["area"], 40 * 60) and close(p["Ix"], 40 * 60 ** 3 / 12) and close(p["Iy"], 60 * 40 ** 3 / 12), "Right plane: section X = model Y, Y = model Z, a 40 x 60 rectangle")
p, _ = section(blk, Plane.XZ.offset(-7.5))
ok(p["frame"]["names"][2] == "-Y" and close(p["area"], 1200) and np.allclose(p["c3"], (0, 7.5, 0)), "an offset moves the cut along the plane's normal (Front: -Y, so -7.5 is y = +7.5)")

# ------------------------------------------------------------------------------------------------------- holes and curves
b = Box(20, 40, 60) - Cylinder(5, 60)
p, _ = section(b, Plane.XY.offset(10))
ok(close(p["area"], 800 - math.pi * 25) and close(p["Ix"], 20 * 40 ** 3 / 12 - math.pi * 5 ** 4 / 4) and close(p["Iy"], 40 * 20 ** 3 / 12 - math.pi * 5 ** 4 / 4), "a rectangle with a 10 mm hole: the hole is taken away (exact, curved edge)")
p, _ = section(Cylinder(10, 30), Plane.XY)
ok(close(p["Ix"], math.pi * 10 ** 4 / 4) and close(p["Iy"], p["Ix"]) and abs(p["Ixy"]) < 1e-6 and p["theta"] is None and close(p["J"], math.pi * 10 ** 4 / 2), "a circle: pi r^4 / 4 about any axis, J = pi r^4 / 2, every axis principal")
p, _ = section(Cylinder(10, 30) - Cylinder(6, 30), Plane.XY)
ok(close(p["Ix"], math.pi * (10 ** 4 - 6 ** 4) / 4) and close(p["area"], math.pi * (100 - 36)), "a tube, outside r 10 and inside r 6")
a_, b_ = 30.0, 10.0
ell = extrude(Face(Wire.make_ellipse(a_, b_)), 20)
p, _ = section(ell, Plane.XY.offset(3))
ok(close(p["area"], math.pi * a_ * b_) and close(p["Ix"], math.pi * a_ * b_ ** 3 / 4) and close(p["Iy"], math.pi * a_ ** 3 * b_ / 4), "an ellipse a = 30, b = 10: Ix = pi a b^3 / 4, Iy = pi a^3 b / 4")
ok(close(p["I1"], p["Iy"]) and abs(abs(p["theta"]) - 90) < 1e-6, "its larger moment is about the Y axis: the I1 axis is at 90 degrees")
s = Sphere(20)
p, _ = section(s, Plane.XY.offset(10))
r = math.sqrt(400 - 100)
ok(close(p["area"], math.pi * r * r) and close(p["Ix"], math.pi * r ** 4 / 4), "a sphere cut 10 mm above its centre: a circle of r = sqrt(400 - 100)")
cone = Cone(20, 10, 40)
areas = []
for z in (-15, 0, 15):
    p, _ = section(cone, Plane.XY.offset(z))
    rz = 20 - 10 * (z + 20) / 40
    areas.append((p["area"], math.pi * rz * rz))
ok(all(close(a, e) for a, e in areas), "a tapered part: the section changes with the offset (" + ", ".join(f"{a:.1f}" for a, _e in areas) + " mm^2)")

# ------------------------------------------------------------------------------------------------------- a section that is not symmetric: an angle
pts = [(0, 0), (60, 0), (60, 6), (6, 6), (6, 40), (0, 40)]                       # an L: legs 60 and 40, thickness 6
ang = extrude(Polygon(*pts, align=None), 100)
p, _ = section(ang, Plane.XY.offset(50))
A, cx, cy, Ix, Iy, Ixy = poly_props(pts)
ok(close(p["area"], A) and np.allclose(p["c"], (cx, cy), atol=1e-7), f"an angle: area {A:g}, centroid ({cx:.3f}, {cy:.3f}) match the polygon integral")
ok(close(p["Ix"], Ix) and close(p["Iy"], Iy) and close(p["Ixy"], Ixy, 1e-6, 1e-4), f"Ix = {Ix:.1f}, Iy = {Iy:.1f}, Ixy = {Ixy:.1f} match the polygon integral (Ixy is not zero and has a sign)")
T = np.array([[Ix, -Ixy], [-Ixy, Iy]])
wv, vv = np.linalg.eigh(T)
ok(close(p["I1"], wv[1]) and close(p["I2"], wv[0]), "principal moments match the polygon's")
th = math.degrees(math.atan2(vv[1, 1], vv[0, 1]))
th = (th + 90) % 180 - 90
ok(abs(p["theta"] - th) < 1e-5 and p["theta"] is not None, f"the I1 axis is at {th:.3f} degrees from the X axis")
a1 = p["axis1"]
Imom = lambda ax: p["Ix"] * ax[0] ** 2 + p["Iy"] * ax[1] ** 2 - 2 * p["Ixy"] * ax[0] * ax[1]          # the moment about an axis with direction (ax, ay)
ok(close(Imom((a1[0], a1[1])), p["I1"]), "the moment about the I1 axis, worked out from Ix, Iy and Ixy, is I1")
ok(close(p["Ix_o"], Ix + A * cy * cy) and close(p["Iy_o"], Iy + A * cx * cx) and close(p["Ixy_o"], Ixy + A * cx * cy), "about the origin axes: the parallel-axis theorem")
# the same angle turned: the principal moments do not change, the angle does
rot = Rot(0, 0, 30) * ang
p2, _ = section(rot, Plane.XY.offset(50))
ok(close(p2["I1"], p["I1"]) and close(p2["I2"], p["I2"]) and close(p2["J"], p["J"]) and abs((p2["theta"] - p["theta"] - 30 + 90) % 180 - 90) < 1e-4, "turned by 30 degrees: I1, I2 and J stay, the angle moves by 30")
# a rectangle turned by 30 degrees: the axis of I1 is its long side's neighbour, at 30 degrees
rect = Rot(0, 0, 30) * Box(20, 40, 10)
p, _ = section(rect, Plane.XY)
ok(abs(p["theta"] - 30) < 1e-5 and close(p["I1"], 20 * 40 ** 3 / 12) and close(p["I2"], 40 * 20 ** 3 / 12) and abs(p["Ixy"]) > 1000, f"a 20 x 40 rectangle turned by 30 degrees: Ixy = {p['Ixy']:.0f}, I1 axis at {p['theta']:.3f}")

# ------------------------------------------------------------------------------------------------------- an I-beam, the usual textbook case
bf, tf, H, tw = 100.0, 10.0, 100.0, 8.0
hw = H - 2 * tf
ibeam = Pos(0, H / 2 - tf / 2, 0) * Box(bf, tf, 200) + Pos(0, -H / 2 + tf / 2, 0) * Box(bf, tf, 200) + Box(tw, hw, 200)
p, _ = section(ibeam, Plane.XY.offset(40))
Ix_ib = bf * H ** 3 / 12 - (bf - tw) * hw ** 3 / 12
Iy_ib = 2 * tf * bf ** 3 / 12 + hw * tw ** 3 / 12
ok(close(p["Ix"], Ix_ib) and close(p["Iy"], Iy_ib) and close(p["area"], 2 * bf * tf + hw * tw), f"an I-beam: Ix = {Ix_ib:.0f}, Iy = {Iy_ib:.0f}, A = {2 * bf * tf + hw * tw:g} (textbook)")
ok(close(p["S"]["+Y"], Ix_ib / (H / 2)) and close(p["rx"], math.sqrt(Ix_ib / p["area"])), "its section modulus Ix / 50 and its radius of gyration")

# ------------------------------------------------------------------------------------------------------- off the origin, the parallel-axis theorem
cyl = Pos(30, 10, 0) * Cylinder(5, 20)
p, _ = section(cyl, Plane.XY.offset(3))
A = math.pi * 25
Ic = math.pi * 5 ** 4 / 4
ok(np.allclose(p["c"], (30, 10)) and np.allclose(p["c3"], (30, 10, 3)), "a cylinder off the origin: centroid (30, 10) in the section axes, (30, 10, 3) in the model")
ok(close(p["Ix"], Ic) and close(p["Ix_o"], Ic + A * 100) and close(p["Iy_o"], Ic + A * 900) and close(p["Ixy_o"], A * 300) and close(p["J_o"], 2 * Ic + A * 1000), "about the origin axes: I + A d^2 (Ix_o = I + A 10^2, Iy_o = I + A 30^2, Ixy_o = A 30 10)")
p, _ = section(cyl, Plane.XZ.offset(-10))                                          # the Front plane at y = 10: through the middle of the cylinder (a rectangle 10 wide, 20 tall)
ok(np.allclose(p["c"], (30, 0)) and close(p["area"], 10 * 20) and close(p["Ix"], 10 * 20 ** 3 / 12), "the cylinder's side cut on the Front plane: x = 30 from the model origin, z = 0")

# ------------------------------------------------------------------------------------------------------- a tilted plane (a plane that is none of the base planes)
s45 = math.sqrt(0.5)
tilt = Plane(origin=(0, 0, 0), x_dir=(1, 0, 0), z_dir=(0, -s45, s45))
rod = Cylinder(10, 200)
p, _ = section(rod, tilt)
semi_a, semi_b = 10.0, 10.0 / s45                                                 # an ellipse: 10 along X, 10 / cos 45 along the tilted Y
ok(close(p["area"], math.pi * semi_a * semi_b) and close(p["Ix"], math.pi * semi_a * semi_b ** 3 / 4) and close(p["Iy"], math.pi * semi_a ** 3 * semi_b / 4), "a round rod cut at 45 degrees: an ellipse, Ix = pi a b^3 / 4 in the tilted plane's own axes")
ok(abs(np.dot(p["frame"]["v"], p["frame"]["u"])) < 1e-12 and p["frame"]["names"][0] == "+X" and p["frame"]["names"][1].startswith("("), "the tilted plane's Y axis is not a model axis: its three components are named")

# ------------------------------------------------------------------------------------------------------- a picked face
face_top = max(ibeam.faces(), key=lambda f: f.center().Z)
fp = Plane(face_top)
p_face, w = section(ibeam, fp, face=face_top)
ok(close(p_face["Ix"], Ix_ib) and close(p_face["Iy"], Iy_ib) and close(p_face["area"], 2 * bf * tf + hw * tw) and not w, "the end face of the I-beam: the same numbers, no warning (the face itself is measured)")
ok(p_face["frame"]["names"][2] == "+Z", "its normal is the outward normal, model +Z")
areas_seen = sorted(round(section(blk, Plane(f), face=f)[0]["area"], 3) for f in blk.faces())
ok(areas_seen == [800, 800, 1200, 1200, 2400, 2400], f"every face of the block measured as itself ({areas_seen})")
# a distance into the part from that face = the plane moved against the outward normal
deeper = Plane(face_top).offset(-30)
p_in, _ = section(ibeam, deeper)
ok(close(p_in["Ix"], Ix_ib) and np.allclose(p_in["c3"], (0, 0, 70)), "30 mm into the beam from its end: the same section, 30 mm lower")

# ------------------------------------------------------------------------------------------------------- misses, touching, several pieces
try:
    section(blk, Plane.XY.offset(100))
    ok(False, "a plane that misses the part is refused")
except sp.SectionError as e:
    ok("does not cut" in str(e), f"a plane that misses the part: '{e}'")
L = Box(20, 20, 20) + Pos(0, 0, 20) * Box(10, 10, 20)                              # a block 20 high with a smaller block on top, the step at z = 10
p, w = section(L, Plane.XY.offset(10))
ok(len(w) == 1 and "exactly in a face" in w[0], "a cut exactly in a face of the part carries a warning (the step at z = 10)")
p, w = section(L, Plane.XY.offset(10.5))
ok(not w and close(p["area"], 100), "moved a little above it: no warning, the small block's 10 x 10")
p, w = section(L, Plane.XY.offset(9.5))
ok(not w and close(p["area"], 400), "moved a little below it: the big block's 20 x 20")
legs = Compound([Pos(-20, 0, 0) * Box(10, 10, 50), Pos(20, 0, 0) * Box(10, 20, 50)])          # two legs that are not connected
p, _ = section(legs, Plane.XY)
a1_, a2_ = 100.0, 200.0
Atot = a1_ + a2_
yc = (a1_ * 0 + a2_ * 0) / Atot
Ix_tot = 10 * 10 ** 3 / 12 + 10 * 20 ** 3 / 12
Iy_tot = 10 * 10 ** 3 / 12 + a1_ * 20 ** 2 + 20 * 10 ** 3 / 12 + a2_ * 20 ** 2 - Atot * ((-20 * a1_ + 20 * a2_) / Atot) ** 2
ok(p["pieces"] == 2 and close(p["area"], Atot) and close(p["Ix"], Ix_tot) and close(p["Iy"], Iy_tot) and abs(p["c"][0] - 20 / 3) < 1e-9, "two separate legs: 2 pieces, measured together about their common centroid (x = 20/3)")

# ------------------------------------------------------------------------------------------------------- drawing data and the report
faces, _ = sp.cut(ibeam, Plane.XY.offset(40))
lines = sp.outline(faces)
ok(len(lines) == 12 and all(len(l) == 2 for l in lines), "the outline of the I-beam: 12 straight edges")
verts, tris = sp.fill(faces)
tri_area = 0.5 * np.linalg.norm(np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]]), axis=1).sum()
ok(close(tri_area, 2 * bf * tf + hw * tw, 1e-6), "the fill triangles add up to the section's area")
hole_faces, _ = sp.cut(b, Plane.XY.offset(10))
vv_, tt_ = sp.fill(hole_faces, 0.01)
ta = 0.5 * np.linalg.norm(np.cross(vv_[tt_[:, 1]] - vv_[tt_[:, 0]], vv_[tt_[:, 2]] - vv_[tt_[:, 0]]), axis=1).sum()
ok(abs(ta - (800 - math.pi * 25)) < 0.5, f"the fill of a rectangle with a hole leaves the hole open (triangles {ta:.2f} mm^2)")
ok(len(sp.outline(hole_faces)) >= 5, "its outline has the rectangle and the circle")

p, w = section(blk, Plane.XY.offset(5))
txt = sp.report("Block", "Top plane, offset 5 mm", p, "mm", 1.0)
for want in ("Section properties of Block", "Cut: Top plane, offset 5 mm", "X = model +X, Y = model +Y", "Area = 800 square mm", "Ix  = 106666.67", "Iy  = 26666.667",
             "Ixy = 0", "J   = Ix + Iy = 133333.33", "I1 = 106666.67", "S = 5333.3333", "mm^4"):
    ok(want in txt, f"report says: {want}")
inch = sp.report("Block", "x", p, "in", 1 / 25.4)
ok("Area = 1.2400025 square in" in inch and f"Ix  = {106666.667 / 25.4 ** 4:.8g}" in inch and "in^4" in inch, "in inches the area and the moments are converted (A / 25.4^2, I / 25.4^4)")
multi = sp.report("Legs", "x", sp.properties(*[sp.cut(legs, Plane.XY)[0], Plane.XY]), "mm", 1.0)
ok("2 separate pieces" in multi, "the report names a section with several pieces")
warned = sp.report("L", "x", p, "mm", 1.0, ["watch out"])
ok("Note: watch out" in warned, "warnings are printed in the report")
sym = sp.report("Rod", "x", section(Cylinder(10, 30), Plane.XY)[0], "mm", 1.0)
ok("every axis through the centroid is a principal axis" in sym, "a round section says every axis is principal")

print("test_solid_section OK")
