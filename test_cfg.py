import pm_model as pm, sk_tools as sk
d = pm.Document(); d.params = {"W": "40", "H": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (20, 20))
m.add_con("dim_h", [("ln", r["lns"][0])], value=20.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=20.0)
sk.solve_model(m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="H")); h = d.add(pm.new_feature("cut", sketch=s["id"], depth="3", end1="blind")); d.rebuild()
print([ (k, l, v) for k, l, v in d.cfg_candidates()])
v0 = d.solid.volume; print("vol", v0, d.status)
for k in ("g:H", f"d:{s['id']}:{m.cons[-2]['id']}" if False else None):
    pass
dims = [c for c in m.cons if c["type"] in ("dim_h", "dim_v")]
kd = f"d:{s['id']}:{dims[0]['id']}"
d.cfg_add_col("g:H"); d.cfg_add_col(kd); d.cfg_add_col(f"s:{h['id']}")
print("cols", [d.cfg_label(k) for k in d.cfg["cols"]])
d.cfg_add("Tall"); d.cfg_set_cell("Tall", "g:H", "30"); d.cfg_set_cell("Tall", kd, 50.0); d.cfg_set_cell("Tall", f"s:{h['id']}", True)
d.cfg_apply("Tall"); d.rebuild(); print("Tall vol", d.solid.volume, "expected", 50 * 20 * 30, d.status)
assert abs(d.solid.volume - 50 * 20 * 30) < 1e-3
d.cfg_apply("Default"); d.rebuild(); print("Default vol", d.solid.volume); assert abs(d.solid.volume - v0) < 1e-3
d2 = pm.Document.from_json(d.to_json()); d2.cfg_apply("Tall"); d2.rebuild(); print("reloaded Tall", d2.solid.volume); assert abs(d2.solid.volume - 50 * 20 * 30) < 1e-3
d.cfg_apply("Tall"); d.params["H"] = "35"; d.rebuild(); print("edit while Tall:", d.cfg_snapshot()["cells"]["Tall"]["g:H"])
d.cfg_rename("Tall", "Tall2"); d.cfg_delete("Default"); print(d.cfg["names"], d.cfg["active"])
print("OK")
