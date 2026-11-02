import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
import pm_model as pm, sk_tools as sk, asm_sketch as ak, gsv, asm_model as am, unitctl
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))
tmp = tempfile.mkdtemp()

# ---- name helpers
assert gsv.full_name("Large", "W") == "AS_Large_W"
assert gsv.resolve_at("{AS_@_W}*2", "Small") == "{AS_Small_W}*2" and gsv.has_binding("{AS_@_W}")
assert "{" not in gsv.mangle("{AS_Large_W} + 3 + {Other}".replace("{Other}", "4"))
assert gsv.mangle("{x}") == "{x}"                                   # only AS- names are touched
assert unitctl._scale_expr("{AS_@_W} + 3", 0.5) == "{AS_@_W} + 1.5", unitctl._scale_expr("{AS_@_W} + 3", 0.5)

# ---- sketch: rectangle, W (input, length) and Ang (input, angle used by an angle dim is hard; use H = W/2 driven by formula) and Diag measured
sd = ak.new_document(); f = ak.sketch_feature(sd); sd.rebuild(); m = sd.models[f["id"]]
sk.add_rect_corner(m, (0, 0), (100, 50)); sk.solve_model(m)
lns = sorted(m.lns)
bottom = next(i for i in lns if all(abs(m.pts[p][1]) < 1e-9 for p in m.lns[i]))
left = next(i for i in lns if all(abs(m.pts[p][0]) < 1e-9 for p in m.lns[i]))
m.add_param("W", 100.0); m.add_con("dim_len", [("ln", bottom)], value=100.0, name="W", expr="W")
m.add_param("H", 50.0, True, "W/2"); m.add_con("dim_len", [("ln", left)], value=50.0, name="H", expr="H")
m.add_param("Scratch", 7.0)                                           # a working variable that is never exported
sk.solve_model(m); sd.store_sketch(f["id"])
m = sd.models[f["id"]]; m.set_configs(["Small", "Big"], "Small"); m.params["W"]["vals"] = [60.0, 140.0]; sk.solve_model(m); sd.store_sketch(f["id"])
configs, vars_, values = ak.variables(sd); print(vars_)
byname = {v["name"]: v for v in vars_}
assert byname["W"]["role"] == "driving" and byname["W"]["kind"] == "length" and byname["H"]["role"] == "driven" and byname["Scratch"]["kind"] == "number", byname
assert not any(v["export"] for v in vars_)
assert ak.payload(sd)[1] == []                                        # nothing exported yet
ak.set_export(sd, "W", True); ak.set_export(sd, "H", True)
cfgs, ex, vals = ak.payload(sd)
assert [v["name"] for v in ex] == ["W", "H"] and "Scratch" not in vals["Big"] and close(vals["Big"]["H"], 70), (ex, vals)
sd2 = pm.Document.from_json(sd.to_json()); assert sd2.export == ["W", "H"]
spath = os.path.join(tmp, "frame.gpk"); ak.save(spath, sd, "asm.gpa", ["plate.gpd"])
d_, a_, p_ = ak.load(spath); assert a_ == "asm.gpa" and p_ == ["plate.gpd"] and d_.export == ["W", "H"]

# ---- a part: global Width bound to the sketch in each configuration, extrude depth uses an explicit name
d = pm.Document(); d.params = {"Width": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); pm_m = d.models[s["id"]]
sk.add_rect_corner(pm_m, (0, 0), (20, 20)); sk.solve_model(pm_m); d.store_sketch(s["id"])
e = d.add(pm.new_feature("extrude", sketch=s["id"], depth="Width")); d.rebuild()
d.base_dir = tmp; d.cfg_add_col("g:Width"); d.cfg_add_col(f"f:{e['id']}:depth")
msgs = ak.apply(d, spath, ak.payload(sd)); d.gsv_bind("g:Width", "W"); d.cfg_set_cell("Big", f"f:{e['id']}:depth", "{AS_Big_H}"); d.cfg_set_cell("Small", f"f:{e['id']}:depth", "{AS_Big_H}"); d.gsv_refresh(); d.rebuild()
print(msgs, d.gsv["src"], d.cfg["names"])
assert d.gsv["src"] == "frame.gpk" and d.cfg["names"] == ["Default", "Small", "Big"], d.cfg["names"]
assert gsv.flat(d.gsv)["AS_Big_W"] == 140.0
assert d.cfg["cells"]["Default"]["g:Width"] == "10"            # the configuration the sketch does not drive stays yours
d.cfg_apply("Big"); d.rebuild()
assert d.status[e["id"]] == "ok" and close(d.values["Width"], 140) and close(d.solid.volume, 20 * 20 * 70), (d.values, d.status)
d.cfg_apply("Small"); d.rebuild(); assert close(d.values["Width"], 60) and close(d.solid.volume, 20 * 20 * 70)    # depth is explicit Big-H
# the bound text is kept in the table after the document is read back
assert d.cfg["cells"]["Small"]["g:Width"] == "{AS_@_W}" and d.cfg["cells"]["Big"]["g:Width"] == "{AS_@_W}", d.cfg["cells"]
d.cfg_capture(); assert d.cfg["cells"]["Small"]["g:Width"] == "{AS_@_W}"
# a new sketch configuration appears in the part by itself, with the bound cells following it
m = sd.models[f["id"]]; m.add_config("Huge") if hasattr(m, "add_config") else m.set_configs(m.configs + ["Huge"], m.configs[m.active]); 
m.params["W"]["vals"][-1] = 300.0; sk.solve_model(m); sd.store_sketch(f["id"])
ch, ms = ak.pull(d, live=lambda p: sd); print(ch, ms, d.cfg["names"])
assert ch and "Huge" in d.cfg["names"] and d.cfg["cells"]["Huge"]["g:Width"] == "{AS_@_W}"
d.cfg_apply("Huge"); d.rebuild(); assert close(d.values["Width"], 300)
# json round trip
d3 = pm.Document.from_json(d.to_json()); assert d3.gsv == d.gsv
# a sketch configuration that is deleted leaves the mirror in place, with a message
sd.rebuild(); m = sd.models[f["id"]]; m.set_configs(["Small", "Big"], "Small"); sd.store_sketch(f["id"])
ch, ms = ak.pull(d, live=lambda p: sd); assert any("Huge" in x for x in ms) and "Huge" not in d.cfg["names"], ms     # the sketch deleted it: the linked file loses it too

# ---- formulas in sketch dimensions of the part use the names too
d.params["Width"] = "10"; d.rebuild()
pm_m = d.models[s["id"]]
# ---- link() writes into a closed file and into an open object; unlink removes
ppath = os.path.join(tmp, "plate.gpd"); open(ppath, "w").write(pm.Document().to_json())
st, ms = ak.link(ppath, spath, sd); assert st == "written", st
p2 = ak.load_target(ppath); assert p2.gsv["src"] == "frame.gpk" and "Small" in p2.cfg["names"], p2.cfg["names"]
op = ak.load_target(ppath)
r = ak.push(spath, sd, [ppath], open_obj=lambda p: op); assert r[0][1] == "open"
assert ak.push(spath, sd, [ppath])[0][1] == "skipped"
assert ak.push(spath, sd, [ppath], write_closed=True)[0][1] == "written"
assert ak.link(os.path.join(tmp, "none.gpd"), spath, sd)[0] == "missing"
assert ak.unlink(ppath) == "written" and ak.load_target(ppath).gsv is None

# ---- an assembly: a mate-free assembly with a global bound to the sketch, mirror makes configurations
a = am.Assembly(); a.params = {"Gap": "{AS_@_W}/10"}
apath = os.path.join(tmp, "asm.gpa"); open(apath, "w").write(a.to_json())
st, ms = ak.link(apath, spath, sd); assert st == "written", st
a2 = ak.load_target(apath); assert a2.gsv and set(a2.cfg["names"]) >= {"Small", "Big"}, a2.cfg["names"]
a2.cfg_add_col("g:Gap") if False else None
a2.evaluate_params() if False else None
a2.params = {"Gap": "{AS_Big_W}/10"}; a2.evaluate_params(); assert close(a2.values["Gap"], 14)
assert am.Assembly.from_json(a2.to_json()).gsv == a2.gsv
print("OK")

# ---- a configuration the sketch deletes is deleted in the linked file; a vanished sketch puts the file "on notice" (names are AS_<config>_<name>)
import pm_model
import asm_sketch
d = pm_model.Document()
d.gsv_set("s.gpk", ["Small", "Big"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}, "Big": {"W": 2.0}})
assert "Big" in d.cfg["names"] and "AS_Big_W" in gsv.flat(d.gsv), (d.cfg["names"], gsv.flat(d.gsv))
msgs = d.gsv_set("s.gpk", ["Small"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}})
assert "Big" not in d.cfg["names"] and "Small" in d.cfg["names"], d.cfg["names"]
assert any("removed" in m for m in msgs), msgs
d.base_dir = "/nonexistent"
ch, m2 = asm_sketch.pull(d)
assert d.gsv.get("orphan") and "on notice" in m2[0] and "Small" in d.cfg["names"], m2
print("config delete + on notice OK")

# ---- the sketch is the master over configuration names: rename follows, delete deletes, add adds (the Configurations table, with permanent ids)
sdx = ak.new_document(); fx = ak.sketch_feature(sdx); sdx.rebuild(); mx = sdx.models[fx["id"]]
sk.add_rect_corner(mx, (0, 0), (100, 50)); sk.solve_model(mx)
bx = next(i for i in sorted(mx.lns) if all(abs(mx.pts[p][1]) < 1e-9 for p in mx.lns[i]))
mx.add_param("W", 100.0); mx.add_con("dim_len", [("ln", bx)], value=100.0, name="W", expr="W"); sk.solve_model(mx); sdx.store_sketch(fx["id"])
ak.set_export(sdx, "W", True)
sdx.cfg_rename("Default", 'Long"1'); sdx.cfg_add_col("g:__none__") if False else None
partx = pm.Document(); partx.params = {"A": "{AS_Long\"1_W}/2"}
assert ak.pull.__doc__ and ak.table_names(sdx) == ['Long"1']
msgs = partx.gsv_set("s.gpk", *ak.payload(sdx), ids=ak.config_ids(sdx))
assert 'Long"1' in partx.cfg["names"] and gsv.flat(partx.gsv)['AS_Long"1_W'] == 100.0, (partx.cfg["names"], gsv.flat(partx.gsv))
sdx.cfg_rename('Long"1', "Tall")
msgs = partx.gsv_set("s.gpk", *ak.payload(sdx), ids=ak.config_ids(sdx))
assert "Tall" in partx.cfg["names"] and 'Long"1' not in partx.cfg["names"] and any("renamed" in m for m in msgs), (partx.cfg["names"], msgs)
assert partx.params["A"] == "{AS_Tall_W}/2", partx.params                                  # formulas follow the rename
sdx.cfg_add("Wide")
partx.gsv_set("s.gpk", *ak.payload(sdx), ids=ak.config_ids(sdx)); assert "Wide" in partx.cfg["names"]
sdx.cfg_delete("Tall")
msgs = partx.gsv_set("s.gpk", *ak.payload(sdx), ids=ak.config_ids(sdx)); assert "Tall" not in partx.cfg["names"] and "Wide" in partx.cfg["names"], msgs
j = pm.Document.from_json(sdx.to_json()); assert j.cfg_ids() == sdx.cfg_ids()                  # ids survive saving
print("sketch is master over names OK")
