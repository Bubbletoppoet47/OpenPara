import os, math
import pm_model as pm, sk_tools as sk
d = pm.Document()
s = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
d.rebuild()
m = d.models[s["id"]]
sk.add_slot_straight(m, (-20, 0), (20, 0), (20, 5)); sk.add_rect_corner(m, (-30, -20), (30, 20)); sk.solve_model(m)
d.store_sketch(s["id"])
x = d.add(pm.new_feature("extrude", sketch=s["id"], depth="10")); d.rebuild(); print(d.status, d.solid.volume)
