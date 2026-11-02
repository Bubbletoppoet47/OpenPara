import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import pm_model as pm, sk_tools as sk, asm_sketch as ak
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
tmp = tempfile.mkdtemp()

# ---- an assembly sketch: a rectangle whose width W is an input per configuration, height H = W/2 (formula), and the diagonal measured
sd = ak.new_document(); f = ak.sketch_feature(sd); sd.rebuild(); m = sd.models[f["id"]]
sk.add_rect_corner(m, (0, 0), (100, 50)); sk.solve_model(m)
lns = sorted(m.lns)
bottom = next(i for i in lns if all(abs(m.pts[p][1]) < 1e-9 for p in m.lns[i]))
left = next(i for i in lns if all(abs(m.pts[p][0]) < 1e-9 for p in m.lns[i]))
m.add_param("W", 100.0)
m.add_con("dim_len", [("ln", bottom)], value=100.0, name="W", expr="W")
m.add_param("H", 50.0, True, "W/2")
m.add_con("dim_len", [("ln", left)], value=50.0, name="H", expr="H")
sk.solve_model(m)
sd.store_sketch(f["id"])
# configurations Small / Big (W = 60 / 140)
m = sd.models[f["id"]]; m.set_configs(["Small", "Big"], "Small"); m.params["W"]["vals"] = [60.0, 140.0]; sk.solve_model(m); sd.store_sketch(f["id"])
configs, vars_, values = ak.variables(sd)
print(configs, vars_, values)
assert configs == ["Small", "Big"]
names = {v["name"]: v["kind"] for v in vars_}
assert names == {"W": "input", "H": "formula"}, names
assert close(values["Small"]["W"], 60) and close(values["Big"]["W"], 140) and close(values["Big"]["H"], 70), values
spath = os.path.join(tmp, "frame.gpk"); ak.save(spath, sd, ["plate.gpd"])
d2, parts2 = ak.load(spath); assert parts2 == ["plate.gpd"] and ak.variables(d2)[2] == values

# ---- a part with a global Width and an extrude depth; link both one way
d = pm.Document(); d.params = {"Width": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); pm_m = d.models[s["id"]]
sk.add_rect_corner(pm_m, (0, 0), (20, 20)); sk.solve_model(pm_m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="Width")); d.rebuild()
d.base_dir = tmp
d.link_add("frame.gpk", "W", "g:Width"); d.link_add("frame.gpk", "H", f"f:{e['id']}:depth")
try:
    d.link_add("frame.gpk", "W", "g:Nope"); assert False
except pm.ModelError:
    pass
assert d.link_of("g:Width")["var"] == "W"
changed, msgs = ak.refresh_part(d)
print("refresh:", changed, msgs, d.cfg["names"], d.cfg["cols"])
assert changed and not msgs and d.cfg["names"] == ["Default", "Small", "Big"], (msgs, d.cfg["names"])
assert d.cfg["cells"]["Small"]["g:Width"] == "60.0" and d.cfg["cells"]["Big"]["g:Width"] == "140.0", d.cfg["cells"]
d.cfg_apply("Big"); d.rebuild()
assert close(float(d.values["Width"]), 140) and d.status[e["id"]] == "ok" and close(d.solid.volume, 20 * 20 * 70), (d.values, d.solid.volume)
d.cfg_apply("Small"); d.rebuild(); assert close(d.solid.volume, 20 * 20 * 30)
# the part's own edits do not touch the sketch: nothing in the sketch file changed, and an unlinked global stays free
before = open(spath).read(); d.params["Other"] = "3"; d.cfg_add_col("g:Other"); d.cfg_set_cell("Small", "g:Other", "9"); assert open(spath).read() == before
# a change in the sketch comes through again
m = sd.models[f["id"]]; m.params["W"]["vals"][1] = 200.0; sk.solve_model(m); sd.store_sketch(f["id"]); ak.save(spath, sd, ["plate.gpd"])
changed, msgs = ak.refresh_part(d); assert changed and d.cfg["cells"]["Big"]["g:Width"] == "200.0"
assert d.cfg["cells"]["Small"]["g:Other"] == "9"                                   # the part's own column untouched
# json round trip keeps the links
d3 = pm.Document.from_json(d.to_json()); assert d3.links == d.links
# rename of a linked global moves the link
d.rename_global("Width", "Wide"); assert d.link_of("g:Wide")["var"] == "W"
# missing sketch file: a message, no crash
d.links.append({"src": "gone.gpk", "var": "W", "target": "g:Other"}); ch, ms = ak.refresh_part(d); assert any("not found" in x for x in ms), ms
d.links.pop()

# ---- push: into an open part, into a closed part file, nothing for a skipped one
ppath = os.path.join(tmp, "plate.gpd"); d.cfg_apply("Default"); open(ppath, "w").write(d.to_json())
d4 = pm.Document.from_json(open(ppath).read()); d4.base_dir = tmp
m = sd.models[f["id"]]; m.params["W"]["vals"][0] = 80.0; sk.solve_model(m); sd.store_sketch(f["id"])
r = ak.push(spath, sd, [ppath], part_doc=lambda p: d4 if p == ppath else None); print(r); assert r[0][1] == "open"
assert d4.cfg["cells"]["Small"]["g:Wide"] == "80.0"
r = ak.push(spath, sd, [ppath], write_closed=False); assert r[0][1] == "skipped"
r = ak.push(spath, sd, [ppath], write_closed=True); assert r[0][1] == "written", r
assert pm.Document.from_json(open(ppath).read()).cfg["cells"]["Small"]["g:Wide"] == "80.0"
assert ak.push(spath, sd, [os.path.join(tmp, "none.gpd")], write_closed=True)[0][1] == "missing"
print("OK")

# ---- a measured (output) variable: the diagonal of the rectangle, numbers differ per configuration
sd2 = ak.new_document(); f2 = ak.sketch_feature(sd2); sd2.rebuild(); m = sd2.models[f2["id"]]
sk.add_rect_corner(m, (0, 0), (100, 50)); sk.solve_model(m)
lns = sorted(m.lns); bottom = next(i for i in lns if all(abs(m.pts[p][1]) < 1e-9 for p in m.lns[i])); left = next(i for i in lns if all(abs(m.pts[p][0]) < 1e-9 for p in m.lns[i]))
m.add_param("W", 100.0); m.add_con("dim_len", [("ln", bottom)], value=100.0, name="W", expr="W")
m.add_param("Hh", 50.0); m.add_con("dim_len", [("ln", left)], value=50.0, name="Hh", expr="Hh")
corner = [p for p in m.pts if p and abs(m.pts[p][0] - 100) < 1e-6 and abs(m.pts[p][1] - 50) < 1e-6][0]
bl=[p for p in m.pts if p and abs(m.pts[p][0])<1e-6 and abs(m.pts[p][1])<1e-6][0]
m.add_con("coincident", [("pt", 0), ("pt", bl)])
m.add_param("Diag", 0.0, False)
m.add_con("dim_len", [("pt", 0), ("pt", corner)], value=0.0, name="Diag", expr="Diag")
sk.solve_model(m); sd2.store_sketch(f2["id"])
m = sd2.models[f2["id"]]; m.set_configs(["A", "B"], "A"); m.params["W"]["vals"] = [30.0, 80.0]; m.params["Hh"]["vals"] = [40.0, 60.0]; sk.solve_model(m); sd2.store_sketch(f2["id"])
c2, v2, val2 = ak.variables(sd2); print(v2, val2)
assert {v["name"]: v["kind"] for v in v2}["Diag"] == "output"
assert close(val2["A"]["Diag"], 50.0, 1e-4) and close(val2["B"]["Diag"], 100.0, 1e-4), val2
print("OK outputs")
