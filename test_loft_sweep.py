"""Sweep and loft features: volumes against exact answers, direction of twist, errors, patterns, save / load."""
import json
import math

import numpy as np
from build123d import Solid

import pm_model as pm
import sk_tools as sk


def join(m):
    """Tie together points that sit on the same spot (what snapping does when you draw by hand)."""
    ids = list(m.pts)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if math.dist(m.pts[a], m.pts[b]) < 1e-6:
                sk.con(m, "coincident", [("pt", a), ("pt", b)])


def mk(d, plane, *shapes):
    s = d.add(pm.new_feature("sketch", plane=plane))
    d.rebuild()
    m = d.models[s["id"]]
    for fn, args in shapes:
        fn(m, *args)
    join(m)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.rebuild()
    return s


def close(a, b, tol, msg):
    ok = abs(a - b) <= tol * abs(b)
    print(("  ok   " if ok else "  FAIL ") + f"{msg}: {a:.4f} (expected {b:.4f})")
    assert ok, msg


R, L = 3.0, 20.0
# ---- straight sweep of a circle
d = pm.Document()
prof = mk(d, {"base": "Top"}, (sk.add_circle, ((0, 0), (R, 0))))
path = mk(d, {"base": "Front"}, (sk.add_line, ((0, 0), (0, L))))
f = d.add(pm.new_feature("sweep", sketch=prof["id"], path=path["id"], merge=True))
d.rebuild()
print("straight sweep:", d.status[f["id"]])
assert d.status[f["id"]] == "ok", d.status[f["id"]]
close(d.solid.volume, math.pi * R * R * L, 1e-6, "straight pipe volume")
bb = d.solid.bounding_box()
close(bb.max.Z - bb.min.Z, L, 1e-6, "pipe length")

# ---- path that starts at the other end gives the same pipe; reverse flag works too
f["reverse"] = True
d.rebuild()
assert d.status[f["id"]] == "ok"
close(d.solid.volume, math.pi * R * R * L, 1e-6, "reversed path, same volume")
f["reverse"] = False

# ---- line then arc (Pappus: area x length of the path centre line)
d2 = pm.Document()
prof2 = mk(d2, {"base": "Top"}, (sk.add_circle, ((0, 0), (R, 0))))
Rb = 10.0
path2 = mk(d2, {"base": "Front"}, (sk.add_line, ((0, 0), (0, 10))))
m2 = d2.models[path2["id"]]
sk.add_arc_3pt(m2, (0, 10), (Rb, 10 + Rb), (Rb * (1 - math.cos(math.pi / 4)), 10 + Rb * math.sin(math.pi / 4)))
join(m2)
sk.solve_model(m2)
d2.store_sketch(path2["id"])
f2 = d2.add(pm.new_feature("sweep", sketch=prof2["id"], path=path2["id"]))
d2.rebuild()
print("line + arc:", d2.status[f2["id"]])
assert d2.status[f2["id"]] == "ok", d2.status[f2["id"]]
close(d2.solid.volume, math.pi * R * R * (10 + Rb * math.pi / 2), 1e-4, "pipe along a line and a quarter circle")

# ---- sharp corner: two cylinders mitred; round corners are a little smaller
d3 = pm.Document()
prof3 = mk(d3, {"base": "Top"}, (sk.add_circle, ((0, 0), (R, 0))))
path3 = mk(d3, {"base": "Front"}, (sk.add_line, ((0, 0), (0, L))), (sk.add_line, ((0, L), (L, L))))
f3 = d3.add(pm.new_feature("sweep", sketch=prof3["id"], path=path3["id"]))
d3.rebuild()
print("L path:", d3.status[f3["id"]])
assert d3.status[f3["id"]] == "ok", d3.status[f3["id"]]
close(d3.solid.volume, 2 * math.pi * R * R * L, 0.01, "mitred corner: two cylinders")
f3["corners"] = "round"
d3.rebuild()
assert d3.status[f3["id"]] == "ok", d3.status[f3["id"]]
assert 0.95 * 2 * math.pi * R * R * L < d3.solid.volume < 2 * math.pi * R * R * L * 1.001
print("  ok   round corners:", round(d3.solid.volume, 2))

# ---- twist: a 8 x 4 bar twisted 90 degrees over 20 mm, against build123d's own twisted extrusion
d4 = pm.Document()
prof4 = mk(d4, {"base": "Top"}, (sk.add_rect_corner, ((-4, -2), (4, 2))))
path4 = mk(d4, {"base": "Front"}, (sk.add_line, ((0, 0), (0, L))))
f4 = d4.add(pm.new_feature("sweep", sketch=prof4["id"], path=path4["id"], twist_on=True, twist="90"))
d4.rebuild()
print("twist:", d4.status[f4["id"]])
assert d4.status[f4["id"]] == "ok", d4.status[f4["id"]]
close(d4.solid.volume, 8 * 4 * L, 1e-3, "twisted bar volume (same as the straight bar)")
from build123d import Face, Location
ref = Solid.extrude_linear_with_rotation(d4.profile(d4.feature(prof4["id"]))[0], (0, 0, 0), (0, 0, L), 90)


def slice_overlap(sol, other, z):
    cut = Face.make_rect(100, 100).moved(Location((0, 0, z)))
    fa, fb = sol.intersect(cut).faces(), other.intersect(cut).faces()
    return (fa[0] & fb[0]).area / fb[0].area


# cross-sections (a boolean between two near-identical twisted solids is unreliable, slices are not)
for z in (5, 10, 15):
    close(slice_overlap(d4.solid, ref, z), 1.0, 2e-3, f"twist matches the exact helical extrusion at z={z}")
f4["twist"] = "-90"
d4.rebuild()
assert d4.status[f4["id"]] == "ok", d4.status[f4["id"]]
ov = slice_overlap(d4.solid, ref, 10)
assert ov < 0.9, "a negative twist must turn the other way"
print("  ok   negative twist turns the other way (slice overlap at z=10:", round(ov, 3), ")")
f4["twist"] = "0"
d4.rebuild()
close(d4.solid.volume, 8 * 4 * L, 1e-6, "twist 0 = plain sweep")

# ---- twist on a path with a corner is refused with a clear message
f3["twist_on"], f3["twist"] = True, "30"
d3.rebuild()
print("twist + corner:", d3.status[f3["id"]])
assert d3.status[f3["id"]].startswith("error") and "smooth" in d3.status[f3["id"]]

# ---- path errors
d5 = pm.Document()
prof5 = mk(d5, {"base": "Top"}, (sk.add_circle, ((0, 0), (R, 0))))
path5 = mk(d5, {"base": "Front"}, (sk.add_line, ((0, 0), (0, 10))), (sk.add_line, ((5, 0), (5, 10))))
f5 = d5.add(pm.new_feature("sweep", sketch=prof5["id"], path=path5["id"]))
d5.rebuild()
print("two separate lines:", d5.status[f5["id"]])
assert d5.status[f5["id"]].startswith("error") and "chain" in d5.status[f5["id"]]
f5["path"] = prof5["id"]
d5.rebuild()
assert d5.status[f5["id"]].startswith("error") and "different sketches" in d5.status[f5["id"]]
f5["path"] = None
d5.rebuild()
assert d5.status[f5["id"]].startswith("error") and "path" in d5.status[f5["id"]]
print("  ok   path errors are reported")

# ---- sweep cut: a groove along a block
d6 = pm.Document()
base = mk(d6, {"base": "Top"}, (sk.add_rect_corner, ((-20, -20), (20, 20))))
d6.add(pm.new_feature("extrude", sketch=base["id"], depth="10"))
d6.rebuild()
v0 = d6.solid.volume
prof6 = mk(d6, {"base": "Right"}, (sk.add_circle, ((0, 5), (0, 8))))
path6 = mk(d6, {"base": "Top", "offset": "0"}, (sk.add_line, ((-25, 0), (25, 0))))
# the profile (Right plane, x = 0) is a circle of radius 3 centred 5 above the base; the path runs along X through the Right plane
c6 = d6.add(pm.new_feature("sweep_cut", sketch=prof6["id"], path=path6["id"]))
d6.rebuild()
print("sweep cut:", d6.status[c6["id"]], d6.solid.volume if d6.solid else None)
assert d6.status[c6["id"]] == "ok", d6.status[c6["id"]]
assert d6.solid.volume < v0 - 100

# ---- loft: square -> smaller square (frustum)
def sq(d, off, a, plane="Top"):
    return mk(d, {"base": plane, "offset": str(off)}, (sk.add_rect_corner, ((-a / 2, -a / 2), (a / 2, a / 2))))
d7 = pm.Document()
s0, s1 = sq(d7, 0, 10), sq(d7, 12, 4)
l7 = d7.add(pm.new_feature("loft", sections=[s0["id"], s1["id"]]))
d7.rebuild()
print("frustum:", d7.status[l7["id"]])
assert d7.status[l7["id"]] == "ok", d7.status[l7["id"]]
close(d7.solid.volume, 12 / 3 * (100 + 16 + 40), 1e-4, "frustum volume")
bb = d7.solid.bounding_box()
close(bb.max.Z - bb.min.Z, 12, 1e-6, "loft height")
# order of the sections does not change the shape
l7["sections"] = [s1["id"], s0["id"]]
d7.rebuild()
assert d7.status[l7["id"]] == "ok"
close(d7.solid.volume, 12 / 3 * (100 + 16 + 40), 1e-4, "frustum, sections in the other order")

# ---- loft: circle -> square -> circle, sections far apart; sanity bounds
d8 = pm.Document()
a = mk(d8, {"base": "Top"}, (sk.add_circle, ((0, 0), (5, 0))))
b = sq(d8, 10, 8)
c = mk(d8, {"base": "Top", "offset": "20"}, (sk.add_circle, ((0, 0), (3, 0))))
l8 = d8.add(pm.new_feature("loft", sections=[a["id"], b["id"], c["id"]]))
d8.rebuild()
print("three sections:", d8.status[l8["id"]], d8.solid.volume if d8.solid else None)
assert d8.status[l8["id"]] == "ok", d8.status[l8["id"]]
assert math.pi * 9 * 20 < d8.solid.volume < 64 * 20 * 1.3
assert d8.solid.is_valid
l8["ruled"] = True
d8.rebuild()
assert d8.status[l8["id"]] == "ok"
print("  ok   ruled loft:", round(d8.solid.volume, 1))

# ---- loft errors
d9 = pm.Document()
x = sq(d9, 0, 5)
y = mk(d9, {"base": "Top", "offset": "5"}, (sk.add_rect_corner, ((0, 0), (4, 4))), (sk.add_circle, ((20, 20), (22, 20))))
z = sq(d9, 0, 3)
l9 = d9.add(pm.new_feature("loft", sections=[x["id"]]))
d9.rebuild()
assert d9.status[l9["id"]].startswith("error") and "two" in d9.status[l9["id"]]
l9["sections"] = [x["id"], y["id"]]
d9.rebuild()
print("two regions:", d9.status[l9["id"]])
assert d9.status[l9["id"]].startswith("error") and "closed regions" in d9.status[l9["id"]]
l9["sections"] = [x["id"], z["id"]]
d9.rebuild()
print("same place:", d9.status[l9["id"]])
assert d9.status[l9["id"]].startswith("error") and "same place" in d9.status[l9["id"]]
print("  ok   loft errors are reported")

# ---- loft cut and a pattern of a loft boss
d10 = pm.Document()
bs = mk(d10, {"base": "Top"}, (sk.add_rect_corner, ((-20, -20), (20, 20))))
d10.add(pm.new_feature("extrude", sketch=bs["id"], depth="20"))
d10.rebuild()
v0 = d10.solid.volume
t0, t1 = sq(d10, 20, 12), sq(d10, 8, 4)
lc = d10.add(pm.new_feature("loft_cut", sections=[t0["id"], t1["id"]]))
d10.rebuild()
print("loft cut:", d10.status[lc["id"]])
assert d10.status[lc["id"]] == "ok", d10.status[lc["id"]]
close(v0 - d10.solid.volume, 12 / 3 * (144 + 16 + 48), 1e-3, "pocket volume")

d11 = pm.Document()
b0, b1 = sq(d11, 0, 6), sq(d11, 8, 3)
lb = d11.add(pm.new_feature("loft", sections=[b0["id"], b1["id"]]))
d11.rebuild()
v1 = d11.solid.volume
pt = d11.add(pm.new_feature("pattern", ptype="linear", features=[lb["id"]], dir1="X", count="3", spacing="20"))
d11.rebuild()
print("pattern of a loft:", d11.status[pt["id"]])
assert d11.status[pt["id"]] == "ok", d11.status[pt["id"]]
close(d11.solid.volume, 3 * v1, 1e-6, "three lofted bosses")

# ---- save / load, rebuild, copy
for doc, name in ((d, "sweep"), (d7, "loft"), (d10, "loft cut")):
    txt = doc.to_json()
    back = pm.Document.from_json(txt)
    back.rebuild()
    close(back.solid.volume, doc.solid.volume, 1e-9, f"{name}: file round trip")
    json.loads(txt)

# ---- the sketches a feature uses
assert set(d.feature_sketches(f)) == {prof["id"], path["id"]}
assert set(d7.feature_sketches(l7)) == {s0["id"], s1["id"]}
print("\nALL OK")
