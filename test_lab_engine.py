"""The Constraint Lab's Experimental mate engine (dev_addons/constraint_lab/lab_engine.py) is the robust one, and the real engine is untouched:
every solvable pick pair of the Mate Matrix ends on the mate from every start pose (including exactly half a turn and 1.5 m away), several mates together
(a pin in a hole, a chain, a redundant mate, a conflict) come out right, an angle between points is a plain error instead of a crash, a solve that hits
something unexpected puts every part back, a part that was edited since the mate was made is still found (and an ambiguous one is refused), and a solve
gives the same answer twice.  No Qt."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "constraint_lab")]
import numpy as np
from build123d import Box, Pos
import asm_model as am, lab_engine as le, lab_matrix as lm

# ---- the real engine does not have any of it
assert not hasattr(am.Assembly, "_lm") and not hasattr(am.Assembly, "_restarts") and "MateError" in am.__dict__ and le.MateError is am.MateError

# ---- the Mate Matrix: nothing solvable fails, nothing crashes
r = lm.run(le)
t = lm.totals(r)
assert t["FAIL"] == 0 and t["STILL"] == 0 and t["EXC"] == 0 and t["ok"] > 1400 and t["score"] == 1.0, dict(t)
assert lm.run(le, mates=["angle"], kinds=["point", "plane"], n_starts=2)["cells"][("point", "point", "angle")] == ["ERR", "ERR"], "angle on a point: a message, not a crash"
# ---- several mates together, from every start pose
sc = lm.run_scenarios(le)
for name, outs in sc["outcomes"].items():
    assert outs == ["ok"] * len(outs), (name, outs)
assert len(sc["outcomes"]) == len(lm.SCENARIOS)


# ---- an unexpected error in the middle of a solve: every part is put back, and it is a MateError the window can show
def corner():
    P = {"plate": Box(80, 80, 10), "block": Box(30, 30, 30)}
    A = le.Assembly(); A.solid_fn = lambda c: P[c["path"]]
    plate = A.add_component("plate", fixed=True); blk = A.add_component("block", pos=(100, 40, 70), fixed=False); blk["rv"] = [0.4, -0.2, 0.3]
    face = lambda s, k: lm._face(P[s], k)
    m = A.add_mate("coincident", [{"c": blk["id"], "k": "face", "r": le.face_ref(face("block", "-z"))}, {"c": plate["id"], "k": "face", "r": le.face_ref(face("plate", "+z"))}])
    return P, A, plate, blk, m
P, A, plate, blk, m = corner()
A.prepare(m); assert A.solve() and abs(blk["pos"][2] - 20) < 1e-6
blk["pos"], blk["rv"] = [100.0, 40.0, 70.0], [0.4, -0.2, 0.3]
orig, n = le.Assembly.mate_residual, {"calls": 0}
def flaky(self, mate, poses=None):
    n["calls"] += 1
    if n["calls"] > 25:
        raise ValueError("boom")
    return orig(self, mate, poses)
le.Assembly.mate_residual = flaky
try:
    try:
        A.solve(); raise SystemExit("a Python error inside the solve must come out as a MateError")
    except am.MateError as ex:
        assert "put back" in str(ex) and "boom" in str(ex), str(ex)
finally:
    le.Assembly.mate_residual = orig
assert blk["pos"] == [100.0, 40.0, 70.0] and blk["rv"] == [0.4, -0.2, 0.3], "nothing is left half moved"
# a position that is not a number is refused up front
blk["pos"][0] = float("nan")
try:
    A.solve(); raise SystemExit("a NaN pose must be refused")
except am.MateError as ex:
    assert "not a number" in str(ex)
blk["pos"][0] = 100.0

# ---- the same solve twice from the same start gives the same poses
def poses():
    P, A, plate, blk, m = corner(); A.prepare(m); A.solve(); return blk["pos"], blk["rv"]
assert poses() == poses()

# ---- a part edited after the mate was made
P, A, plate, blk, m = corner()
A.prepare(m); assert A.solve() and abs(blk["pos"][2] - 20) < 1e-6
P["plate"] = Box(80, 80, 20)                                           # the plate is thicker now: its top face moved up by 5 mm (more than the 2 mm of an exact match)
A._cache.clear()
assert A.solve() and abs(blk["pos"][2] - 25) < 1e-6, blk["pos"]       # the mate follows the face it was made on
stepped = Box(80, 80, 10) + Pos(0, 0, 10) * Box(20, 20, 10)            # two upward faces, at z = 5 and z = 15
try:
    le.local_entity({"k": "face", "r": {"c": [0, 0, 10], "g": "PLANE", "n": [0, 0, 1]}}, stepped)
    raise SystemExit("two equally likely faces must be refused")
except am.MateError as ex:
    assert "more than one" in str(ex), str(ex)
assert abs(le.local_entity({"k": "face", "r": {"c": [0, 0, 5.4], "g": "PLANE", "n": [0, 0, 1]}}, stepped)["p"][2] - 5) < 1.0
try:
    le.local_entity({"k": "face", "r": {"c": [0, 0, 900], "g": "PLANE", "n": [0, 0, 1]}}, stepped)
    raise SystemExit("a face that is nowhere near must still be reported as gone")
except am.MateError as ex:
    assert "no longer exists" in str(ex)

print("OK lab engine")
