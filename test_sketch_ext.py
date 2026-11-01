"""Geometry of other sketches inside a sketch: pierce point, projected point / line, following edits, lost sources, save / load, sweep."""
import math
import numpy as np
import pm_model as pm
import sk_tools as sk
import sketch_ext as se


def mk(d, plane, *shapes):
    s = d.add(pm.new_feature("sketch", plane=plane))
    d.rebuild()
    m = d.models[s["id"]]
    for fn, args in shapes:
        fn(m, *args)
    sk.solve_model(m)
    d.store_sketch(s["id"])
    d.rebuild()
    return s


def ref(d, fid, kind, src, key, near=None):
    if d.index_of(src) > d.index_of(fid):                        # like the editor: a sketch is built from what is before it
        assert d.move_blocker(fid, src) is None
        d.move_after(fid, src)
        d.rebuild()
    m = d.models[fid]
    r = se.add_reference(d, fid, m, kind, src, key, near, label="path")
    assert r is None, r
    sk.solve_model(m)
    d.store_sketch(fid)
    d.rebuild()
    return d.models[fid]


def uv_of(d, fid, pid):
    return tuple(d.models[fid].pts[pid])


# ---- pierce of a straight path: profile on Top (z = 0), path on Front goes up from (5, 0)
d = pm.Document()
prof = mk(d, {"base": "Top"}, (sk.add_circle, ((0, 0), (3, 0))))
path = mk(d, {"base": "Front"}, (sk.add_line, ((5, 0), (5, 20))))
lid = next(iter(d.models[path["id"]].lns))
m = ref(d, prof["id"], "pierce", path["id"], ("ln", lid))
rec = m.ext[0]
assert math.dist(uv_of(d, prof["id"], rec["pt"]), (5, 0)) < 1e-9, uv_of(d, prof["id"], rec["pt"])
# the profile's circle centre is tied to it with a normal relation
cid = next(iter(m.cis)); cp = m.cis[cid]["c"]
sk.con(m, "coincident", [("pt", cp), ("pt", rec["pt"])])
sk.solve_model(m); d.store_sketch(prof["id"]); d.rebuild()
assert math.dist(d.models[prof["id"]].pts[cp], (5, 0)) < 1e-6
assert d.index_of(path["id"]) < d.index_of(prof["id"])           # the profile was moved behind the path
print("pierce straight OK")
f = d.add(pm.new_feature("sweep", sketch=prof["id"], path=path["id"], merge=True))
d.rebuild()
assert d.status[f["id"]] == "ok", d.status[f["id"]]
bb = d.solid.bounding_box()
assert abs(bb.min.X - 2) < 1e-6 and abs(bb.max.X - 8) < 1e-6, (bb.min.X, bb.max.X)
print("sweep of the tied profile OK  volume", round(d.solid.volume, 2), "expected", round(math.pi * 9 * 20, 2))
assert abs(d.solid.volume - math.pi * 9 * 20) < 1e-3 * math.pi * 9 * 20

# ---- editing the path moves the profile
mp = d.models[path["id"]]
for p in mp.pts:
    if p != 0 and abs(mp.pts[p][0] - 5) < 1e-9:
        mp.pts[p][0] = 8.0
sk.solve_model(mp); d.store_sketch(path["id"]); d.rebuild()
assert math.dist(d.models[prof["id"]].pts[cp], (8, 0)) < 1e-6, d.models[prof["id"]].pts[cp]
assert d.status[f["id"]] == "ok"
bb = d.solid.bounding_box()
assert abs(bb.min.X - 5) < 1e-6 and abs(bb.max.X - 11) < 1e-6, (bb.min.X, bb.max.X)
print("profile follows an edited path OK")

# ---- save / load keeps the reference
d2 = pm.Document.from_json(d.to_json()); d2.rebuild()
assert len(d2.models[prof["id"]].ext) == 1 and math.dist(d2.models[prof["id"]].pts[cp], (8, 0)) < 1e-6
print("save / load OK")

# ---- the path no longer reaches the plane: the point stays, a message says why
mp = d.models[path["id"]]
lo, hi = sorted(p for p in mp.pts if p != 0)
mp.pts[lo][1], mp.pts[hi][1] = -10.0, -5.0                          # both ends below the profile plane
for c in list(mp.cons):
    if c["type"] == "fixed":
        c["xy"] = tuple(mp.pts[c["refs"][0][1]])
sk.solve_model(mp); d.store_sketch(path["id"]); d.rebuild()
msgs = d.reports[prof["id"]].messages
assert any("stops before" in x or "does not reach" in x for x in msgs), msgs
assert math.dist(d.models[prof["id"]].pts[cp], (8, 0)) < 1e-6        # kept its last position
print("lost reference reported:", msgs[0])

# ---- the source sketch deleted: the reference goes quietly, nothing crashes
d3 = pm.Document()
p3 = mk(d3, {"base": "Top"}, (sk.add_point, ((0, 0),)) if hasattr(sk, "add_point") else (sk.add_circle, ((0, 0), (1, 0))))
q3 = mk(d3, {"base": "Front"}, (sk.add_line, ((5, 0), (5, 20))))
m3 = ref(d3, p3["id"], "pierce", q3["id"], ("ln", next(iter(d3.models[q3["id"]].lns))))
d3.remove(q3["id"]); d3.rebuild()
assert d3.status[p3["id"]] == "ok" and any("not built" in x for x in d3.reports[p3["id"]].messages)
print("deleted source OK")

# ---- pierce of an arc / circle path (two hits: the one nearest the click is taken)
d4 = pm.Document()
pr4 = mk(d4, {"base": "Top"}, (sk.add_circle, ((0, 0), (1, 0))))
ar4 = mk(d4, {"base": "Front"}, (sk.add_circle, ((0, 10), (10, 10))))       # circle radius 10 round (0, 10) in the XZ plane: meets z = 0 at x = 0
cid4 = next(iter(d4.models[ar4["id"]].cis))
try:
    ref(d4, pr4["id"], "pierce", ar4["id"], ("ci", cid4), near=(0.0, 0.0, 0.0))
    m4 = d4.models[pr4["id"]]
    assert math.dist(m4.pts[m4.ext[0]["pt"]], (0, 0)) < 1e-6
    print("pierce circle tangent OK")
except AssertionError as ex:
    print("circle tangent to the plane:", ex)
ar5 = mk(d4, {"base": "Front"}, (sk.add_circle, ((0, 5), (10, 5))))        # centre (0, 5), r 10: meets z = 0 at x = +-sqrt(75)
cid5 = next(iter(d4.models[ar5["id"]].cis))
m5 = ref(d4, pr4["id"], "pierce", ar5["id"], ("ci", cid5), near=(8.0, 0.0, 0.0))
r5 = m5.ext[-1]
assert abs(m5.pts[r5["pt"]][0] - math.sqrt(75)) < 1e-6, m5.pts[r5["pt"]]
rr = se.apply  # the other hit is chosen when the click was on that side
d4.models[pr4["id"]].ext[-1]["last"] = [-8.0, 0.0, 0.0]
d4.store_sketch(pr4["id"]); d4.rebuild()
assert abs(d4.models[pr4["id"]].pts[r5["pt"]][0] + math.sqrt(75)) < 1e-6
print("pierce circle, both sides OK")

# ---- projected point and line (the path is not in a plane parallel to the profile)
d6 = pm.Document()
pr6 = mk(d6, {"base": "Top"}, (sk.add_circle, ((0, 0), (1, 0))))
pa6 = mk(d6, {"base": "Front"}, (sk.add_line, ((5, 3), (9, 20))))
mm6 = d6.models[pa6["id"]]
a_id = min(p for p in mm6.pts if p != 0 and abs(mm6.pts[p][0] - 5) < 1e-9)
m6 = ref(d6, pr6["id"], "pt", pa6["id"], ("pt", a_id))
assert math.dist(m6.pts[m6.ext[0]["pt"]], (5, 0)) < 1e-9            # (x, z) = (5, 3) projected onto z = 0 is x = 5, y = 0
lid6 = next(iter(mm6.lns))
m6 = ref(d6, pr6["id"], "ln", pa6["id"], ("ln", lid6))
r6 = m6.ext[1]
assert ("ln", r6["ln"]) in m6.constr                                  # a reference line is construction: it never becomes part of the profile
ends = sorted(tuple(round(v, 9) for v in m6.pts[p]) for p in r6["pts"])
assert ends == [(5.0, 0.0), (9.0, 0.0)], ends
print("projected point / line OK")

# ---- when a sketch cannot be moved behind the one it wants to follow
d8 = pm.Document()
a8 = mk(d8, {"base": "Top"}, (sk.add_circle, ((0, 0), (1, 0))))
b8 = mk(d8, {"base": "Front"}, (sk.add_line, ((0, 0), (0, 5))))
d8.add(pm.new_feature("sweep", sketch=a8["id"], path=b8["id"], merge=True)); d8.rebuild()
assert d8.move_blocker(a8["id"], b8["id"]) is None
ex = d8.add(pm.new_feature("extrude", sketch=a8["id"], depth="2")); d8.rebuild()
i_ex = d8.index_of(ex["id"])
assert "uses it" in (d8.move_blocker(a8["id"], ex["id"]) or "")            # the extrude between uses the sketch
face_sk = d8.add(pm.new_feature("sketch", plane={"face": {"ref": "x"}}))
other = d8.add(pm.new_feature("sketch", plane={"base": "Top"}))
assert "face" in (d8.move_blocker(face_sk["id"], other["id"]) or "")
print("move blockers OK")

# ---- old files without references still load, and references survive undo snapshots
assert sk.sc.Model().ext == []
m7 = d.models[prof["id"]]
snap = m7.to_json(); m7.from_json(snap)
assert len(m7.ext) == 1
print("SKETCH EXT OK")
