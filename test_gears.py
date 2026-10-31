"""Spur gear geometry checked against independent facts, not against the formulas that built it."""
import math

from build123d import Axis, Circle, Edge, Face, Location, Plane, Vector, extrude

import gears


def ok(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    assert cond, msg


P = {"module": 2, "teeth": 20, "pressure": 20, "width": 10, "bore": 8}
D = gears.dims(P)
# textbook values: m=2, z=20, 20 deg
for k, want in (("d", 40), ("da", 44), ("df", 35), ("db", 37.5877)):
    ok(abs(D[k] - want) < 1e-3, f"{k} = {D[k]:.4f} (textbook {want})")
ok(abs(D["base_pitch"] - math.pi * 2 * math.cos(math.radians(20))) < 1e-12, "base pitch = pi m cos(a)")
ok(abs(D["base_pitch"] - 2 * math.pi * D["rb"] / 20) < 1e-12, "base pitch = base circumference / z")
ok(not gears.dims({**P, "teeth": 20})["undercut"] and gears.dims({**P, "teeth": 10})["undercut"], "undercut warning below ~17 teeth")
ok(gears.dims({**P, "teeth": 17})["undercut"] and not gears.dims({**P, "teeth": 18})["undercut"], "undercut limit between 17 and 18 teeth at 20 deg")

s = gears.spur_gear(P)
ok(s.is_valid, "the solid is valid")
# exact tooth count: one cylindrical tip face per tooth
tips = [f for f in s.faces() if f.geom_type.name == "CYLINDER" and
        abs(max(math.hypot(v.X, v.Y) for v in f.vertices()) - D["ra"]) < 1e-6]
ok(len(tips) == 20, f"exactly 20 teeth ({len(tips)} tip faces)")
for z in (7, 12, 31, 48):
    sz = gears.spur_gear({**P, "teeth": z})
    n = len([f for f in sz.faces() if f.geom_type.name == "CYLINDER" and
             abs(max(math.hypot(v.X, v.Y) for v in f.vertices()) - gears.dims({**P, "teeth": z})["ra"]) < 1e-6])
    ok(n == z and sz.is_valid, f"z={z}: {n} teeth, valid")

# the flank really is an involute: its normal is tangent to the base circle (distance origin -> normal line = rb)
base, rpt, lpt = gears.tooth_edges(D)
worst = 0.0
for e in [e for e in base if e.geom_type.name == 'BSPLINE']:
    for t in (0.1, 0.3, 0.5, 0.7, 0.9):
        pt, tg = e.position_at(t), e.tangent_at(t)
        dist = abs(pt.X * tg.X + pt.Y * tg.Y) / math.hypot(tg.X, tg.Y)       # distance origin -> normal line = |P . T|
        worst = max(worst, abs(dist - D["rb"]))
ok(worst < 2e-3, f"flank normals are tangent to the base circle (worst error {worst:.2e} mm)")

# tooth thickness on the pitch circle = pi m / 2 (measured on the built solid)
sec = s.intersect(Face.make_rect(200, 200).moved(Location((0, 0, 5))))
face = sec.faces()[0]
ring = Edge.make_circle(D["rp"]).moved(Location((0, 0, 5)))
cut = face.intersect(ring)
length = sum(e.length for e in cut.edges())
want = 20 * math.pi * 2 / 2
ok(abs(length - want) < 5e-3 * want, f"tooth thickness on the pitch circle: total {length:.3f}, expected {want:.3f}")

# backlash makes the teeth thinner by the stated amount
sb = gears.spur_gear({**P, "backlash": 0.1})
fb = sb.intersect(Face.make_rect(200, 200).moved(Location((0, 0, 5)))).faces()[0]
lb = sum(e.length for e in fb.intersect(ring).edges())
ok(abs((length - lb) / 20 - 0.1 / 2 * 1.0) < 0.01 or abs((length - lb) / 20 - 0.1) < 0.01, f"backlash 0.1 thins each tooth by {(length - lb) / 20:.4f}")

# bore and volume sanity
ok(abs(s.bounding_box().max.X - 22) < 1e-6, "outside diameter 44")
ok(0.80 * math.pi * 20 ** 2 * 10 < s.volume + math.pi * 16 * 10 < math.pi * 22 ** 2 * 10, "volume between pitch cylinder and tip cylinder")

# deterministic
ok(abs(gears.spur_gear(P).volume - s.volume) < 1e-9, "same inputs, same solid")

# two meshing gears: no overlap through a full tooth pitch, clear overlap if pushed together
z1, z2 = 20, 30
g1p, g2p = {**P, "teeth": z1, "bore": 0}, {**P, "teeth": z2, "bore": 0}
d1, d2 = gears.dims(g1p), gears.dims(g2p)
g1, g2 = gears.spur_gear(g1p), gears.spur_gear(g2p)
cd = d1["rp"] + d2["rp"]
vmax = 0.0
for k in range(0, 9):
    a1 = k / 8 * 360 / z1                                   # turn gear 1 through one tooth pitch
    a2 = -a1 * z1 / z2 + 180 + 180 / z2 * 0                 # gear 2 turns the other way; a tooth of gear 2 faces gear 1 (at 180 deg a space does)
    A = g1.moved(Location((0, 0, 0), (0, 0, 1), a1))
    B = g2.moved(Location((cd, 0, 0), (0, 0, 1), a2 + 180 / z2))
    v = (A & B).volume
    vmax = max(vmax, v)
ok(vmax < 0.5, f"meshing pair: largest overlap over a tooth pitch {vmax:.4f} mm3 (gear volume {g1.volume:.0f})")
B = g2.moved(Location((cd - 0.6, 0, 0), (0, 0, 1), 180 / z2 + 180))
ok((g1 & B).volume > 5, "pushed 0.6 mm closer the same pair overlaps clearly (the check can fail)")



# ---------------------------------------------------------------- helical and herringbone
H = {"module": 2, "teeth": 20, "pressure": 20, "width": 20, "bore": 0, "helix": 20}
DH = gears.dims(H)
ok(abs(DH["d"] - 2 * 20 / math.cos(math.radians(20))) < 1e-9, f"helical pitch diameter = m_n z / cos(beta) = {DH['d']:.4f}")
ok(abs(math.tan(DH["at"]) - math.tan(math.radians(20)) / math.cos(math.radians(20))) < 1e-12, "tan(a_t) = tan(a_n) / cos(beta)")
ok(abs(DH["base_pitch"] - 2 * math.pi * DH["rb"] / 20) < 1e-12, "base pitch = base circumference / z in the transverse section")


def sl(sol, z):
    return sol.intersect(Face.make_rect(300, 300).moved(Location((0, 0, z)))).faces()[0]


def sl0(sol, z):
    return sl(sol, z).moved(Location((0, 0, -z)))        # the slice brought down to z = 0 so two heights can be compared


def overlap(a, b):
    return (a & b).area / a.area


spur_face = gears.profile_face(DH)
for hand, sgn in (("right", 1), ("left", -1)):
    g = gears.helical_gear({**H, "hand": hand})
    ok(g.is_valid and len(g.solids()) == 1, f"{hand}-hand helical gear is one valid solid")
    ok(abs(g.volume - spur_face.area * 20) < 5e-4 * g.volume, f"{hand}: volume = outline area x width ({g.volume:.1f})")
    turn = gears.twist_deg(DH, 20)
    ok(abs(math.degrees(math.atan(math.radians(turn) * DH["rp"] / 20)) - 20) < 1e-9, f"{hand}: twist {turn:.3f} deg over 20 mm gives helix angle 20 deg on the pitch cylinder")
    for z in (0.01, 10, 19.99):
        want = spur_face.rotate(Axis.Z, sgn * gears.twist_deg(DH, z)).moved(Location((0, 0, z)))
        ov = overlap(sl(g, z), want)
        ok(ov > 0.995, f"{hand}: section at z={z} is the outline turned by {sgn * gears.twist_deg(DH, z):.3f} deg (overlap {ov:.4f})")

# hands are opposite: the two helical gears are mirror images, not the same shape
gr, gl = gears.helical_gear({**H, "hand": "right"}), gears.helical_gear({**H, "hand": "left"})
ok(overlap(sl0(gr, 5), sl0(gl, 5)) < 0.9, "right and left hand differ 5 mm up (about half a tooth pitch apart)")

# herringbone: mirror symmetric about the middle plane, V pointing the same way, groove option
hb = gears.herringbone_gear(H)
ok(hb.is_valid and len(hb.solids()) == 1, "herringbone is one valid solid")
ok(abs(hb.volume - spur_face.area * 20) < 5e-4 * hb.volume, f"herringbone volume = outline area x width ({hb.volume:.1f})")
for dz in (2, 5, 9.9):
    ov = overlap(sl0(hb, 10 - dz), sl0(hb, 10 + dz))
    ok(ov > 0.995, f"herringbone sections {dz} mm below and above the middle are identical (overlap {ov:.4f})")
ok(overlap(sl0(hb, 0.01), sl0(hb, 10)) < 0.9 and overlap(sl0(hb, 0.01), sl0(hb, 19.99)) > 0.995, "ends line up, the middle is turned")
hg = gears.herringbone_gear({**H, "groove": 4})
ok(hg.is_valid and len(hg.solids()) == 1, "herringbone with a 4 mm groove is one valid solid")
core = abs(hg.volume - (spur_face.area * 16 + math.pi * DH["rf"] ** 2 * 4))
ok(core < 1e-3 * hg.volume, "groove volume = root-circle disc 4 mm thick")

# meshing helical pair (opposite hands) never overlaps; same hand collides
z1, z2 = 20, 30
q1, q2 = {**H, "teeth": z1}, {**H, "teeth": z2}
d1, d2 = gears.dims(q1), gears.dims(q2)
cd = d1["rp"] + d2["rp"]
a, bq = gears.helical_gear({**q1, "hand": "right"}), gears.helical_gear({**q2, "hand": "left"})
worst = 0.0
for k in range(0, 7):
    a1 = k / 6 * 360 / z1
    A = a.moved(Location((0, 0, 0), (0, 0, 1), a1))
    B = bq.moved(Location((cd, 0, 0), (0, 0, 1), -a1 * z1 / z2 + 180 + 180 / z2))
    worst = max(worst, (A & B).volume)
ok(worst < 1.0, f"right/left helical pair meshes: largest overlap {worst:.4f} mm3 (gear volume {a.volume:.0f})")
Bs = gears.helical_gear({**q2, "hand": "right"})
worst2 = max((a.moved(Location((0, 0, 0), (0, 0, 1), k / 6 * 360 / z1)) & Bs.moved(Location((cd, 0, 0), (0, 0, 1), -(k / 6 * 360 / z1) * z1 / z2 + 180 + 180 / z2))).volume for k in range(0, 7))
ok(worst2 > 20, f"two right-hand gears do not mesh (overlap {worst2:.1f} mm3), so the hand really matters")
print("\nALL OK")
