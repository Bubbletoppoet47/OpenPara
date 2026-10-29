import math
import pm_model as pm, sk_tools as sk
def mk(plane, shapes):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane=plane)); d.rebuild(); m = d.models[s["id"]]
    for sh in shapes:
        sh[0](m, *sh[1], *sh[2:])
    sk.solve_model(m); d.store_sketch(s["id"]); return d, s
# revolve a rectangle (offset from the sketch Y axis) full turn -> tube
d, s = mk({"base": "Front"}, [(sk.add_rect_corner, ((10, 0), (20, 30)))])
r = d.add(pm.new_feature("revolve", sketch=s["id"], angle="360", axis="sy")); d.rebuild(); print("revolve", d.status, d.solid.volume, "expected", math.pi * (400 - 100) * 30)
assert abs(d.solid.volume - math.pi * 300 * 30) < 1e-3
r["angle"] = "90"; d.rebuild(); print("90deg", d.solid.volume); assert abs(d.solid.volume - math.pi * 300 * 30 / 4) < 1e-3
r["angle"] = "360"
# revolve about a construction centerline of the sketch
d2, s2 = mk({"base": "Front"}, [(sk.add_rect_corner, ((10, 0), (20, 30))), (sk.add_line, ((0, -5), (0, 40)), True)])
r2 = d2.add(pm.new_feature("revolve", sketch=s2["id"], axis="auto")); d2.rebuild(); print("centerline axis", d2.status, d2.solid.volume); assert abs(d2.solid.volume - math.pi * 300 * 30) < 1e-3
# cut revolve: groove into a block
d3, s3 = mk({"base": "Front"}, [(sk.add_rect_corner, ((-30, 0), (30, 30)))]); d3.add(pm.new_feature("extrude", sketch=s3["id"], depth="60"))
s4 = d3.add(pm.new_feature("sketch", plane={"base": "Front"})); d3.rebuild(); m4 = d3.models[s4["id"]]; sk.add_rect_corner(m4, (5, 10), (10, 20)); d3.store_sketch(s4["id"])
c = d3.add(pm.new_feature("revolve_cut", sketch=s4["id"], axis="sy", angle="360")); d3.rebuild(); print("revolve cut", d3.status[c["id"]], d3.solid.volume)
# linear pattern of a boss
d5, s5 = mk({"base": "Top"}, [(sk.add_rect_corner, ((0, 0), (40, 40)))]); d5.add(pm.new_feature("extrude", sketch=s5["id"], depth="10"))
s6 = d5.add(pm.new_feature("sketch", plane={"base": "Top"})); d5.rebuild()
# boss on top face: use plane offset
d5.feature(s6["id"])["plane"] = {"base": "Top", "offset": "10"}; d5.rebuild(); m6 = d5.models[s6["id"]]; sk.add_circle(m6, (5, 5), (8, 5)); d5.store_sketch(s6["id"])
b = d5.add(pm.new_feature("extrude", sketch=s6["id"], depth="5")); d5.rebuild(); v0 = d5.solid.volume; print("boss", d5.status[b["id"]], v0)
p = d5.add(pm.new_feature("pattern", ptype="linear", features=[b["id"]], dir1="X", count="3", spacing="15")); d5.rebuild(); print("linear pattern", d5.status[p["id"]], d5.solid.volume, "expected", v0 + 2 * math.pi * 9 * 5)
assert abs(d5.solid.volume - (v0 + 2 * math.pi * 9 * 5)) < 1e-3
p["dir2_on"] = True; p["dir2"] = "Y"; p["count2"] = "2"; p["spacing2"] = "20"; d5.rebuild(); print("2D pattern", d5.solid.volume, "expected", v0 + 5 * math.pi * 9 * 5); assert abs(d5.solid.volume - (v0 + 5 * math.pi * 9 * 5)) < 1e-3
# circular pattern about Z of the same boss, 4 copies
q = d5.add(pm.new_feature("pattern", ptype="circular", features=[b["id"]], axis="Z", count="4", angle="360")); p["suppressed"] = True; d5.rebuild(); print("circular pattern", d5.status[q["id"]], d5.solid.volume)
# mirror the boss about the Right plane (x -> -x): the boss at x=5 goes to -5 (off the body) -> solid grows by one disc
m_ = d5.add(pm.new_feature("mirror", features=[b["id"]], plane={"base": "Right"})); q["suppressed"] = True; d5.rebuild(); print("mirror", d5.status[m_["id"]], d5.solid.volume)
# body pattern / mirror
m_["source"] = "body"; d5.rebuild(); print("mirror body", d5.status[m_["id"]], d5.solid.volume, d5.solid.bounding_box().min.X)
print("OK")
