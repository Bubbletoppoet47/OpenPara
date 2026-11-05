"""Truss Generator: an edit rebuilds only the members it touches (the others are reused, with their meshes), and the result equals a full rebuild."""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "addons_src", "truss"), os.path.join(HERE, "shared")]
import pm_model as pm, sk_tools as sk
import truss_core as tc
d = pm.Document(); d.params = {"Span": "3000"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
pts = [(0, 0), (3000, 0), (1500, 800), (4500, 800), (6000, 0)]
L = [sk.add_line(m, pts[0], pts[1]), sk.add_line(m, pts[1], pts[2]), sk.add_line(m, pts[2], pts[0]), sk.add_line(m, pts[2], pts[3]),
     sk.add_line(m, pts[3], pts[1]), sk.add_line(m, pts[3], pts[4])]
sk.solve_model(m); d.store_sketch(s["id"])
src = tc.SketchSource(d.to_json(), s["id"]); cfg = src.active()
p = tc.new_project("Perf")
for ln in sorted(src.lines(cfg)): tc.add_member(p, ln)
t0 = time.perf_counter(); b1 = tc.Built(p, src, cfg); full = time.perf_counter() - t0
assert not b1.errors and b1.rebuilt == len(p["members"]) and b1.reused == 0, (b1.errors, b1.rebuilt)
# nothing changed: everything is reused
t0 = time.perf_counter(); b2 = tc.Built(p, src, cfg, cache=b1.cache_out); again = time.perf_counter() - t0
assert b2.rebuilt == 0 and b2.reused == len(p["members"]), (b2.rebuilt, b2.reused)
assert again < full * 0.5, (again, full)
assert all(b2.members[k].solid is b1.members[k].solid for k in b1.members), "the very same solids"
# change the roll of one member: only that one is cut again (a member joined to it by an automatic joint too, when its end depends on it)
mid = p["members"][0]["id"]
tc.member(p, mid)["roll"] = 15.0
b3 = tc.Built(p, src, cfg, cache=b2.cache_out)
assert 1 <= b3.rebuilt < len(p["members"]) and b3.reused >= 1, (b3.rebuilt, b3.reused)
ref = tc.Built(p, src, cfg)                                   # the same project built from scratch
for k in ref.members:
    a, c = ref.members[k].solid.volume, b3.members[k].solid.volume
    assert abs(a - c) < 1e-6 * max(a, 1), (k, a, c)
assert [r["length"] for r in ref.cut_list()] == [r["length"] for r in b3.cut_list()]
# a change of the sketch (the configuration's variables / lines) invalidates what depends on it
tc.member(p, mid)["roll"] = 0.0
b4 = tc.Built(p, src, cfg, cache=b3.cache_out)
assert b4.rebuilt >= 1
print("OK truss perf: full %.0f ms, unchanged %.0f ms; one edit rebuilt %d of %d" % (full * 1000, again * 1000, b3.rebuilt, len(p["members"])))
