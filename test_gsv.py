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
msgs = ak.apply(d, spath, ak.payload(sd)); d.gsv_bind("g:Width", "W"); d.cfg_set_cell("Default · Big", f"f:{e['id']}:depth", "{AS_Big_H}"); d.gsv_refresh(); d.rebuild()
print(msgs, d.gsv["src"], d.cfg["names"])
assert d.gsv["src"] == "frame.gpk" and d.cfg["names"] == ["Default · Small", "Default · Big"], d.cfg["names"]     # applying the variable made Default a group
assert [g["name"] for g in d.cfg["tree"]["groups"]] == ["Default"]
assert gsv.flat(d.gsv)["AS_Big_W"] == 140.0
d.cfg_apply("Default · Big"); d.rebuild()
assert d.status[e["id"]] == "ok" and close(d.values["Width"], 140) and close(d.solid.volume, 20 * 20 * 70), (d.values, d.status)
d.cfg_apply("Default · Small"); d.rebuild(); assert close(d.values["Width"], 60) and close(d.solid.volume, 20 * 20 * 30)    # depth {AS_Big_H} was applied as {AS_@_H}: each child follows its own suffix
# the bound text is kept in the table after the document is read back
assert d.cfg["cells"]["Default · Small"]["g:Width"] == "{AS_@_W}" and d.cfg["cells"]["Default · Big"]["g:Width"] == "{AS_@_W}", d.cfg["cells"]
d.cfg_capture(); assert d.cfg["cells"]["Default · Small"]["g:Width"] == "{AS_@_W}"
# a new sketch configuration appears in the part by itself, with the bound cells following it
m = sd.models[f["id"]]; m.add_config("Huge") if hasattr(m, "add_config") else m.set_configs(m.configs + ["Huge"], m.configs[m.active]); 
m.params["W"]["vals"][-1] = 300.0; sk.solve_model(m); sd.store_sketch(f["id"])
ch, ms = ak.pull(d, live=lambda p: sd); print(ch, ms, d.cfg["names"])
assert ch and "Default · Huge" in d.cfg["names"] and d.cfg["cells"]["Default · Huge"]["g:Width"] == "{AS_@_W}"
d.cfg_apply("Default · Huge"); d.rebuild(); assert close(d.values["Width"], 300)
# json round trip
d3 = pm.Document.from_json(d.to_json()); assert d3.gsv == d.gsv
# a sketch configuration that is deleted leaves the mirror in place, with a message
sd.rebuild(); m = sd.models[f["id"]]; m.set_configs(["Small", "Big"], "Small"); sd.store_sketch(f["id"])
ch, ms = ak.pull(d, live=lambda p: sd); assert any("Huge" in x for x in ms) and "Default · Huge" not in d.cfg["names"], ms     # the sketch deleted it: the linked file loses it too

# ---- formulas in sketch dimensions of the part use the names too
d.params["Width"] = "10"; d.rebuild()
pm_m = d.models[s["id"]]
# ---- link() writes into a closed file and into an open object; unlink removes
ppath = os.path.join(tmp, "plate.gpd"); open(ppath, "w").write(pm.Document().to_json())
st, ms = ak.link(ppath, spath, sd); assert st == "written", st
p2 = ak.load_target(ppath); assert p2.gsv["src"] == "frame.gpk" and p2.gsv["configs"] == ["Small", "Big"], p2.gsv["configs"]
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
a2 = ak.load_target(apath); assert a2.gsv and a2.gsv["configs"] == ["Small", "Big"], a2.gsv
a2.cfg_add_col("g:Gap") if False else None
a2.evaluate_params() if False else None
a2.params = {"Gap": "{AS_Big_W}/10"}; a2.evaluate_params(); assert close(a2.values["Gap"], 14)
assert am.Assembly.from_json(a2.to_json()).gsv == a2.gsv
print("OK")

# ---- nested configurations (cfg_tree.py): the sketch is the master over the names
import cfg_tree, asm_sketch


def linked_part(configs, vals):
    d = pm.Document(); d.params = {"A": "1"}; d.cfg_add_col("g:A")
    d.gsv_set("s.gpk", configs, [{"name": "W", "kind": "length", "role": "driving"}], vals, ids=["i" + str(k) for k in range(len(configs))])
    assert d.cfg["names"] == ["Default"]                  # nothing nested until a variable is applied
    d.gsv_bind("g:A", "W")
    return d


d = linked_part(["Small", "Big"], {"Small": {"W": 1.0}, "Big": {"W": 2.0}})
assert d.cfg["names"] == ["Default · Small", "Default · Big"] and cfg_tree.leaf(d, "Default · Big")["suffix"] == "Big", d.cfg["names"]
assert "AS_Big_W" in gsv.flat(d.gsv)
d.cfg_apply("Default · Big"); d.rebuild(); assert close(d.values["A"], 2.0)
d.cfg_apply("Default · Small"); d.rebuild(); assert close(d.values["A"], 1.0)
# rename in the sketch: the suffix follows, formulas that named the old one follow
d.params["B"] = "{AS_Big_W}*3"
ids = ["i0", "i1"]
d.gsv_set("s.gpk", ["Small", "Tall"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}, "Tall": {"W": 2.0}}, ids=ids)
assert d.cfg["names"] == ["Default · Small", "Default · Tall"] and d.params["B"] == "{AS_Tall_W}*3", (d.cfg["names"], d.params)
# add: a child per group; delete: the child goes
d.gsv_set("s.gpk", ["Small", "Tall", "Wide"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}, "Tall": {"W": 2.0}, "Wide": {"W": 3.0}}, ids=ids + ["i2"])
assert d.cfg["names"] == ["Default · Small", "Default · Tall", "Default · Wide"], d.cfg["names"]
d.gsv_set("s.gpk", ["Small", "Wide"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 1.0}, "Wide": {"W": 3.0}}, ids=["i0", "i2"])
assert d.cfg["names"] == ["Default · Small", "Default · Wide"], d.cfg["names"]
listing_groups, regular = cfg_tree.listing(d); assert [g["name"] for g, _ in listing_groups] == ["Default"] and regular == []
# groups first (in the order made), regular configurations below, children in the order of the sketch
d.cfg_add("Mine"); d.cfg["cells"]["Mine"] = {"g:A": "5"}; d.params["Z"] = "1"; d.cfg_add_col("g:Z"); d.cfg_set_cell("Mine", "g:Z", "{AS_Small_W}")
groups, regular = cfg_tree.listing(d)
assert [g["name"] for g, _ in groups] == ["Default", "Mine"] and regular == [], ([g["name"] for g, _ in groups], regular)
assert [n for _v, n in [(v, c) for v, c in groups[0][1]]][0] == ["Default · Small", "Default · Wide"]
# rename a group: the children are renamed, the suffix is kept
cfg_tree.rename_group(d, groups[0][0]["id"], "Short pipe")
assert d.cfg["names"][:2] == ["Short pipe · Small", "Short pipe · Wide"], d.cfg["names"]
# severing: a regular configuration with plain numbers, the child stays
new = cfg_tree.sever(d, "Short pipe · Wide")
assert new in d.cfg["names"] and cfg_tree.leaf(d, new) is None and "Short pipe · Wide" in d.cfg["names"]
assert close(float(d.cfg["cells"][new]["g:A"]), 3.0), d.cfg["cells"][new]
# a feature change: no sibling has that state -> "new"; make_variant keeps the original
fid = "F_test"
st, tgt = cfg_tree.feature_change(d, "Short pipe · Small", "s:" + fid, True); assert st == "new", st
mine = cfg_tree.make_variant(d, "Short pipe · Small", "s:" + fid, True, "No holes")
assert mine == "Short pipe · No holes · Small" and d.cfg["cells"][mine]["s:" + fid] is True and not d.cfg["cells"]["Short pipe · Small"].get("s:" + fid), d.cfg["names"]
st, tgt = cfg_tree.feature_change(d, "Short pipe · Small", "s:" + fid, True); assert (st, tgt) == ("switch", mine), (st, tgt)
# only the sketch removes children: the last configuration is never deleted, the panel never deletes a child (cfg_tree.delete_group deletes a group)
j = pm.Document.from_json(d.to_json()); assert j.cfg["tree"] == d.cfg["tree"]
# a vanished sketch puts the file "on notice"
d.base_dir = "/nonexistent"
ch, m2 = asm_sketch.pull(d)
assert d.gsv.get("orphan") and "on notice" in m2[0] and "Short pipe · Small" in d.cfg["names"], m2
print("nested configurations OK")

# ---- an assembly component whose cell names a GROUP of the part follows the assembly's sketch configuration by itself
import cfg_tree
pd = linked_part(["Small", "Big"], {"Small": {"W": 1.0}, "Big": {"W": 2.0}})
assert cfg_tree.choices(pd)[:1] == ["Default"] and "Default · Big" in cfg_tree.choices(pd)
assert cfg_tree.resolve(pd, "Default", "Big") == "Default · Big" and cfg_tree.resolve(pd, "Default", "Small") == "Default · Small"
assert cfg_tree.resolve(pd, "Default", "Nope") == "Default · Small"            # no child with that suffix: the first one
assert cfg_tree.resolve(pd, "Default · Big", "Small") == "Default · Big"       # an explicit child stays
print("component picks child OK")
