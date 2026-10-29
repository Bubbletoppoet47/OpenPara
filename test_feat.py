import math
import pm_model as pm, sk_tools as sk
def mk(plane={"base": "Top"}, shapes=()):
    d = pm.Document(); s = d.add(pm.new_feature("sketch", plane=plane)); d.rebuild(); m = d.models[s["id"]]
    for fn, args in shapes: fn(m, *args)
    sk.solve_model(m); d.store_sketch(s["id"]); return d, s
def vol(d): return d.solid.volume
# boss blind
d, s = mk(shapes=[(sk.add_rect_corner, ((0, 0), (40, 20)))]); e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild(); print("blind", d.status, vol(d)); assert abs(vol(d) - 8000) < 1e-3
e["end1"] = "mid"; d.rebuild(); b = d.solid.bounding_box(); print("mid z", b.min.Z, b.max.Z); assert abs(b.min.Z + 5) < 1e-6
e["end1"] = "blind"; e["dir2"] = True; e["depth2"] = "5"; d.rebuild(); b = d.solid.bounding_box(); print("dir2", b.min.Z, b.max.Z, vol(d)); assert abs(b.min.Z + 5) < 1e-6 and abs(b.max.Z - 10) < 1e-6
e["dir2"] = False; e["draft_on"] = True; e["draft"] = "5"; d.rebuild(); print("draft", d.status, vol(d)); assert vol(d) < 8000
e["draft_out"] = True; d.rebuild(); print("draft out", vol(d)); assert vol(d) > 8000
e["draft_on"] = False; e["thin"] = True; e["thickness"] = "2"; d.rebuild(); print("thin", d.status, vol(d)); assert abs(vol(d) - (800 - 36 * 16) * 10) < 1e-3
e["thin_side"] = "outside"; d.rebuild(); print("thin out", vol(d)); assert abs(vol(d) - (240 + math.pi * 4) * 10) < 1e-3
e["thin"] = False
# hole + draft
d2, s2 = mk(shapes=[(sk.add_rect_corner, ((0, 0), (40, 20))), (sk.add_circle, ((20, 10), (25, 10)))]); e2 = d2.add(pm.new_feature("extrude", sketch=s2["id"], depth="10", draft_on=True, draft="3")); d2.rebuild(); print("draft with hole", d2.status, vol(d2))
# contours: only the hole region? (regions: outer-with-hole). two disjoint rects, pick one
d3, s3 = mk(shapes=[(sk.add_rect_corner, ((0, 0), (10, 10))), (sk.add_rect_corner, ((30, 0), (50, 10)))]); e3 = d3.add(pm.new_feature("extrude", sketch=s3["id"], depth="5")); d3.rebuild(); print("two", vol(d3))
info = d3.region_info(s3); print("regions", info); e3["pts"] = [list(info[0][1])]; d3.rebuild(); print("one region", vol(d3))
# cut default direction on a base plane: sketch at z=0 plane under a boss -> auto dir goes up into the material
d4, s4 = mk(shapes=[(sk.add_rect_corner, ((0, 0), (40, 20)))]); d4.add(pm.new_feature("extrude", sketch=s4["id"], depth="10"))
s5 = d4.add(pm.new_feature("sketch", plane={"base": "Top"})); d4.rebuild(); m5 = d4.models[s5["id"]]; sk.add_circle(m5, (20, 10), (25, 10)); d4.store_sketch(s5["id"])
c = d4.add(pm.new_feature("cut", sketch=s5["id"], depth="4")); d4.rebuild(); print("cut from base plane", d4.status, vol(d4), c.get("dir")); assert abs(vol(d4) - (8000 - math.pi * 25 * 4)) < 1e-3
c["reverse"] = True; d4.rebuild(); print("cut reversed", d4.status[c["id"]]); assert d4.status[c["id"]].startswith("error")
c["reverse"] = False; c["end1"] = "through"; d4.rebuild(); assert abs(vol(d4) - (8000 - math.pi * 25 * 10)) < 1e-2
c["flip_side"] = True; d4.rebuild(); print("flip side (keep inside)", d4.status[c["id"]], vol(d4))
# up to face: boss on the Top plane up to a tilted... use a planar face of another body
d6, s6 = mk(shapes=[(sk.add_rect_corner, ((0, 0), (40, 40)))]); d6.add(pm.new_feature("extrude", sketch=s6["id"], depth="30"))
s7 = d6.add(pm.new_feature("sketch", plane={"base": "Top"})); d6.rebuild(); m7 = d6.models[s7["id"]]; sk.add_rect_corner(m7, (5, 5), (10, 10)); d6.store_sketch(s7["id"])
top = max(d6.solid.faces(), key=lambda f: f.center().Z)
c2 = d6.add(pm.new_feature("cut", sketch=s7["id"], depth="1", end1="face", to_face=pm.Document.face_ref(top))); d6.rebuild(); print("cut up to face", d6.status[c2["id"]], vol(d6))
print("OK")
