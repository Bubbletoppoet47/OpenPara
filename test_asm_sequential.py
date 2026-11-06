"""Mates are solved one at a time in the order they were made: earlier mates are trusted and stay exact, a mate that cannot be met is left out and
reported, an edited middle mate is solved against the earlier ones and the later ones are replayed after it."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from build123d import Box, Cylinder, Pos
import asm_model as am
parts = {"H": Box(100, 100, 20) - Pos(20, 0, 0) * Cylinder(5, 30) - Pos(-20, 0, 0) * Cylinder(5, 30), "P": Cylinder(5, 30), "B": Box(20, 20, 10)}
planes = lambda s: [f for f in s.faces() if f.geom_type.name == "PLANE"]
top = lambda s: max(planes(s), key=lambda f: f.center().Z); bot = lambda s: min(planes(s), key=lambda f: f.center().Z)
sidex = lambda s: max(planes(s), key=lambda f: f.center().X)
cyls = lambda s: sorted([f for f in s.faces() if f.geom_type.name == "CYLINDER"], key=lambda f: f.center().X)
R = lambda c, k, r=None: {"c": c["id"], "k": k, "r": r}; fr = am.face_ref
def new():
    A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
    return A, A.add_component("H", fixed=True)
def mate(A, typ, refs, value=None):
    m = A.add_mate(typ, refs); A.prepare(m)
    if value is not None: m["value"] = value
    return m
H = parts["H"]

# 1. order decides who yields: the same three mates, made in a different order, flag a different one
A, h = new(); p = A.add_component("P", pos=(25, 3, 20)); p["rv"] = [0.05, 0.02, 0]
m_c = mate(A, "concentric", [R(h, "face", fr(cyls(H)[1])), R(p, "face", fr(cyls(parts["P"])[0]))])
m_t = mate(A, "coincident", [R(h, "face", fr(top(H))), R(p, "face", fr(bot(parts["P"])))])
m_d = mate(A, "distance", [R(h, "face", fr(sidex(H))), R(p, "origin")], 30.0)         # wants x = 20 as well: agrees
assert A.solve() and all(v == "ok" for v in A.status.values()), A.status
m_d["value"] = 33.0                                                                      # now x = 17 disagrees with the hole at x = 20
ok = A.solve(); assert not ok
assert A.status[m_c["id"]] == "ok" and A.status[m_t["id"]] == "ok" and A.status[m_d["id"]] == am.Assembly.CONFLICT, A.status      # the later one yields
assert np.allclose(p["pos"], [20, 0, 25], atol=1e-4), p["pos"]
# 2. a NEW mate that disagrees is the one reported (it is last), nothing else moves
A, h = new(); p = A.add_component("P", pos=(25, 3, 20))
mate(A, "coincident", [R(h, "face", fr(top(H))), R(p, "face", fr(bot(parts["P"])))])
mate(A, "distance", [R(h, "face", fr(sidex(H))), R(p, "origin")], 33.0); assert A.solve()
before = list(p["pos"])
new_m = A.add_mate("concentric", [R(h, "face", fr(cyls(H)[1])), R(p, "face", fr(cyls(parts["P"])[0]))]); A.prepare(new_m)
A.mates.remove(new_m)
assert not A.solve(extra=[new_m]) and A.status[new_m["id"]] == am.Assembly.CONFLICT
assert np.allclose(p["pos"], before, atol=1e-6), "the preview did not move the held part"
# 3. editing a mate in the middle: the earlier ones stay, the edited one is solved, the later ones are replayed after it
A, h = new(); b = A.add_component("B", pos=(0, 0, 20))
m1 = mate(A, "coincident", [R(h, "face", fr(top(H))), R(b, "face", fr(bot(parts["B"])))])
m2 = mate(A, "distance", [R(h, "face", fr(sidex(H))), R(b, "origin")], 20.0)           # x = 30
p = A.add_component("P", pos=(0, 0, 40))
m3 = mate(A, "coincident", [R(b, "face", fr(top(parts["B"]))), R(p, "face", fr(bot(parts["P"])))])   # the pin stands on the box
assert A.solve() and all(v == "ok" for v in A.status.values())
assert abs(b["pos"][0] - 30) < 1e-4 and abs(p["pos"][2] - (b["pos"][2] + 5 + 15)) < 1e-4
m2["value"] = 5.0                                                                          # edit the middle one: the box slides to x = 45
assert A.solve() and all(v == "ok" for v in A.status.values()), A.status
assert abs(b["pos"][0] - 45) < 1e-4 and abs(b["pos"][2] - 15) < 1e-4, b["pos"]           # the first mate (box on the plate) still exact
assert abs(p["pos"][2] - (b["pos"][2] + 20)) < 1e-4, "the later mate followed"
# an edit that cannot hold with an earlier mate: only the edited one is flagged, the later one still applies
m2["value"] = 5.0
q = mate(A, "distance", [R(h, "face", fr(sidex(H))), R(b, "origin")], 25.0)               # a later mate that disagrees with m2 (x = 45 vs 25)
ok = A.solve(); assert not ok
assert A.status[m1["id"]] == "ok" and A.status[m2["id"]] == "ok" and A.status[m3["id"]] == "ok" and A.status[q["id"]] == am.Assembly.CONFLICT, A.status
# 4. a mate loop that only works together is still solved (together first)
A, h = new(); b = A.add_component("B", pos=(0, 0, 40)); p = A.add_component("P", pos=(60, 0, 40))
mate(A, "coincident", [R(h, "face", fr(top(H))), R(b, "face", fr(bot(parts["B"])))])
mate(A, "coincident", [R(h, "face", fr(top(H))), R(p, "face", fr(bot(parts["P"])))])
mate(A, "distance", [R(b, "origin"), R(p, "origin")], 40.0)
assert A.solve(), A.status
assert abs(np.linalg.norm(np.array(b["pos"]) - np.array(p["pos"])) - 40) < 1e-3
print("OK sequential mates")
