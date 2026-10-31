"""Gear systems: centre distances, profile shift, trains and planetary sets, checked against the real solids."""
import math
import sys

from build123d import Location

import gears
import gearsys as S

fails = []


def ok(c, msg):
    print(("  ok   " if c else "  FAIL ") + msg)
    if not c:
        fails.append(msg)


def vol(x):
    return 0.0 if x is None else x.volume


def put(sol, x, y, turn):
    return sol.moved(Location((x, y, 0), (0, 0, 1), turn))


# ---- numbers
for v in (0.001, 0.0149, 0.1, 1.0):
    a = S.inv_angle(v)
    ok(abs(math.tan(a) - a - v) < 1e-13, f"inv_angle({v}) inverts tan a - a")
D1, D2 = gears.dims(dict(module=2, teeth=20, pressure=20)), gears.dims(dict(module=2, teeth=40, pressure=20))
pc = S.pair_centre(D1, D2)
ok(abs(pc["C"] - 60) < 1e-12 and pc["k"] == 0, "no shift: centre distance m (z1+z2)/2 = 60, no tip shortening")
for hx in (0, 25):
    A = gears.dims(dict(module=2, teeth=20, pressure=20, helix=hx))
    for C in (60.3, 60.5, 61.0):
        C0 = A["mt"] * (20 + 40) / 2
        C = C0 + (C - 60)
        Sx = S.shift_for_centre(A, 40, C)
        B = gears.dims(dict(module=2, teeth=20, pressure=20, helix=hx, shift=Sx))
        ok(abs(S.pair_centre(B, gears.dims(dict(module=2, teeth=40, pressure=20, helix=hx)))["C"] - C) < 1e-9,
           f"helix {hx}: shift {Sx:+.4f} gives centre distance {C:.3f} exactly")
ok(S.shift_for_centre(D1, 40, 20) is None, "an impossible centre distance gives no answer")
cr = S.contact_ratio(D1, D2, 60)
ok(1.5 < cr < 1.8, f"contact ratio of 20/40 teeth, 20 deg: {cr:.3f} (textbook about 1.6)")

# ---- the helical shift term (cos beta): thickness at the pitch circle changes by 2 x_t tan(at) mt on the pitch circle
Hs = gears.dims(dict(module=2, teeth=20, pressure=20, helix=25, shift=0.4))
H0 = gears.dims(dict(module=2, teeth=20, pressure=20, helix=25))
dt = 2 * Hs["rp"] * (gears.half_angle(Hs, Hs["rp"]) - gears.half_angle(H0, H0["rp"]))
want = 2 * 0.4 * 2 * math.tan(Hs["an"])                      # normal-section thickness gain 2 x mn tan(an)
ok(abs(dt * math.cos(Hs["beta"]) - want) < 1e-9,
   f"helical shift: thickness gain on the pitch circle {dt:.4f} mm (transverse); normal-section value {dt * math.cos(Hs['beta']):.4f} vs {want:.4f}")


def overlap_pair(a, b, pa, pb, ra_, rb_, steps=5, z1=None, z2=None):
    """Largest intersection volume while gear a turns through one tooth pitch and b follows (rolling)."""
    worst = 0.0
    za, zb = z1, z2
    for k in range(steps + 1):
        d = k / steps * 360 / za
        A = put(a, pa[0], pa[1], ra_ + d)
        B = put(b, pb[0], pb[1], rb_ - d * za / zb)
        worst = max(worst, vol(A & B))
    return worst


# ---- spur train, centre distance 60.5 -> 40 teeth + shift
g1 = dict(module=2, teeth=20, pressure=20, helix=0, hand="right", width=6, bore=0, backlash=0)
r = S.solve_train(g1, [dict(how="centre", value=60.5)])
ok(abs(r["C"][0] - 60.5) < 1e-9 and r["gears"][1]["teeth"] == 40, f"train: centre distance {r['C'][0]:.6f}, 40 teeth, shift {r['gears'][1]['shift']:+.3f}")
s1, s2 = (gears.make("Spur gear", g) for g in r["gears"])
w = overlap_pair(s1, s2, r["pos"][0], r["pos"][1], r["turn"][0], r["turn"][1], 5, 20, 40)
ok(w < 0.5, f"shifted spur pair meshes: largest overlap {w:.4f} mm3 over a tooth pitch")
w2 = max(vol(put(s1, 0, 0, r["turn"][0]) & put(s2, r["C"][0] - 0.6, 0, r["turn"][1])), 0)
ok(w2 > 5, f"pushed 0.6 mm closer it overlaps ({w2:.1f} mm3)")

# ---- helical train, hands alternate, centre distance by shift (tests the cos(beta) term)
g1h = {**g1, "helix": 22, "width": 8}
mt = 2 / math.cos(math.radians(22))
r = S.solve_train(g1h, [dict(how="centre", value=mt * 30 + 0.3)])
ok([g["hand"] for g in r["gears"]] == ["right", "left"], "helical train: hands alternate")
a, b = (gears.make("Helical gear", g) for g in r["gears"])
w = overlap_pair(a, b, r["pos"][0], r["pos"][1], r["turn"][0], r["turn"][1], 5, r["gears"][0]["teeth"], r["gears"][1]["teeth"])
ok(w < 1.0, f"shifted helical pair (z {r['gears'][0]['teeth']}/{r['gears'][1]['teeth']}, shift {r['gears'][1]['shift']:+.3f}) meshes: overlap {w:.4f} mm3")
w2 = vol(put(a, 0, 0, r["turn"][0]) & put(b, r["C"][0] - 0.6, 0, r["turn"][1]))
ok(w2 > 5, f"pushed 0.6 mm closer: overlap {w2:.1f} mm3")

# ---- three gears with a bend, sized by total span and first ratio
r = S.solve_train(g1, [dict(how="ratio", value=1.5), dict(how="span", value=100.0)], bend=90)
ok(abs(sum(r["C"]) - 100.0) < 1e-9, f"span: centre distances {r['C'][0]:.3f} + {r['C'][1]:.3f} = 100")
ok(abs(math.hypot(r["pos"][2][0] - r["pos"][1][0], r["pos"][2][1] - r["pos"][1][1]) - r["C"][1]) < 1e-9, "gear 3 sits one centre distance from gear 2")
ok(abs(r["pos"][2][0] - r["pos"][1][0]) < 1e-9 and r["pos"][2][1] > 0, "bend 90: gear 3 is straight up from gear 2")
sol = [gears.make("Spur gear", g) for g in r["gears"]]
worst = 0.0
for k in range(5):
    d = k / 4 * 360 / r["gears"][0]["teeth"]
    t1 = r["turn"][0] + d
    t2 = r["turn"][1] - d * r["gears"][0]["teeth"] / r["gears"][1]["teeth"]
    t3 = r["turn"][2] - t2 * 0 + (-(t2 - r["turn"][1])) * r["gears"][1]["teeth"] / r["gears"][2]["teeth"]
    A, B, C3 = put(sol[0], *r["pos"][0], t1), put(sol[1], *r["pos"][1], t2), put(sol[2], *r["pos"][2], t3)
    worst = max(worst, vol(A & B), vol(B & C3))
ok(worst < 0.5, f"three gears with a 90 degree bend mesh: largest overlap {worst:.4f} mm3")
ok(abs(r["total_ratio"] - r["gears"][2]["teeth"] / r["gears"][0]["teeth"]) < 1e-12, "total ratio = z3 / z1")

try:
    S.solve_train(g1, [dict(how="ratio", value=2), dict(how="span", value=70.0)])
    ok(False, "a span too small for gear 3 is refused")
except ValueError as ex:
    ok("only" in str(ex), "a span too small for gear 3 is refused: " + str(ex)[:80])

# ---- tip shortening keeps the clearance: tips never reach the other gear's root
r = S.solve_train(g1, [dict(how="centre", value=60.5)])
assert r["gears"][0]["add"] < 1
d1, d2 = (gears.dims(g) for g in r["gears"])
ok(r["C"][0] - (d1["ra"] + d2["rf"]) > 0.25 * 2 - 1e-9 and r["C"][0] - (d2["ra"] + d1["rf"]) > 0.25 * 2 - 1e-9,
   f"tip clearance kept at >= 0.25 m (x total {r['gears'][1]['shift']:+.3f}, tips shortened by {1 - r['gears'][0]['add']:.3f} m)")

# ---- planetary
base = dict(module=2, pressure=20, helix=0, hand="right")
pl = S.solve_planetary(base, "sun+planet", zs=18, zp=12, n=3, widths={"sun": 6, "planet": 6, "ring": 6}, bores={"sun": 0, "planet": 0})
ok(pl["zr"] == 42 and pl["n_ok"] and pl["valid_n"][:3] == [1, 2, 3], f"ring = sun + 2 planet = {pl['zr']} teeth; planet counts that fit: {pl['valid_n']}")
ok(abs(pl["ratios"]["ring fixed (sun in, carrier out)"] - (1 + 42 / 18)) < 1e-12, "ring-fixed ratio 1 + zr/zs")
bad = S.solve_planetary(base, "sun+planet", zs=18, zp=12, n=7)
ok(not bad["n_ok"] and any("do not work" in t for t in bad["notes"]), "7 planets rejected with suggestions: " + bad["notes"][0][:90])
odd = S.solve_planetary(base, "sun+ring", zs=18, zr=43)
ok(odd["zr"] == 44 and odd["zp"] == 13, "sun + ring with an odd difference is moved to the nearest whole planet")
ring = gears.make("Ring gear", pl["ring"])
sun = gears.make("Spur gear", pl["sun"])
pln = gears.make("Spur gear", pl["planet"])
ok(ring.is_valid and sun.is_valid, "ring and sun are valid solids")


def planet_state(d):
    """Carrier fixed: the sun turns by d, planets spin by -d zs/zp, the ring by -d zs/zr."""
    return d, -d * pl["zs"] / pl["zp"], -d * pl["zs"] / pl["zr"]


worst_s = worst_r = worst_pp = 0.0
for k in range(4):
    ds, dp, dr = planet_state(k / 3 * 360 / pl["zs"])
    sun_k = put(sun, 0, 0, ds)
    ring_k = put(ring, 0, 0, pl["ring_phase"] + dr - pl["ring_phase"] + 0) if False else put(ring, 0, 0, dr)
    planets = []
    for i in range(3):
        phi = math.radians(360 * i / 3)
        P = put(pln, pl["C"] * math.cos(phi), pl["C"] * math.sin(phi), pl["planet_turn"][i] + dp)
        planets.append(P)
        worst_s = max(worst_s, vol(sun_k & P))
        worst_r = max(worst_r, vol(ring_k & P))
    worst_pp = max(worst_pp, vol(planets[0] & planets[1]))
ok(worst_s < 0.5, f"planets mesh the sun: largest overlap {worst_s:.4f} mm3")
ok(worst_r < 0.5, f"planets mesh the ring: largest overlap {worst_r:.4f} mm3")
ok(worst_pp < 1e-6, "planets do not touch each other")
P = put(pln, pl["C"], 0, pl["planet_turn"][0] + 180 / pl["zp"])
ok(vol(ring & P) > 1 or vol(sun & P) > 1, "turned half a tooth the planet collides (the check can fail)")

# helical planetary: sun/planet opposite hands, planet/ring the same
bh = dict(module=2, pressure=20, helix=20, hand="right")
ph = S.solve_planetary(bh, "sun+planet", zs=18, zp=12, n=3, widths={"sun": 6, "planet": 6, "ring": 6}, bores={"sun": 0, "planet": 0})
ok((ph["sun"]["hand"], ph["planet"]["hand"], ph["ring"]["hand"]) == ("right", "left", "left"), "helical planetary hands: sun R, planet L, ring L")
sunh, plnh, ringh = (gears.make("Helical gear", ph["sun"]), gears.make("Helical gear", ph["planet"]), gears.make("Ring gear", ph["ring"]))
worst = 0.0
for k in range(3):
    d = k / 2 * 360 / ph["zs"]
    for i in range(3):
        phi = math.radians(120 * i)
        Pk = put(plnh, ph["C"] * math.cos(phi), ph["C"] * math.sin(phi), ph["planet_turn"][i] - d * ph["zs"] / ph["zp"])
        worst = max(worst, vol(put(sunh, 0, 0, d) & Pk), vol(put(ringh, 0, 0, -d * ph["zs"] / ph["zr"]) & Pk))
ok(worst < 1.0, f"helical planetary meshes: largest overlap {worst:.4f} mm3")

print("\n" + ("ALL OK" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
