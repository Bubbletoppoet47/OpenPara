"""A concentric mate yields to the mates that hold the part: with a conflict the holding mates stay exact and only the concentric one is reported."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from build123d import Box, Cylinder, Pos
import asm_model as am
parts = {"H": Box(100, 100, 20) - Pos(20, 0, 0) * Cylinder(5, 30), "P": Cylinder(5, 30)}
planes = lambda s: [f for f in s.faces() if f.geom_type.name == "PLANE"]
top = lambda s: max(planes(s), key=lambda f: f.center().Z); bot = lambda s: min(planes(s), key=lambda f: f.center().Z)
sidex = lambda s: max(planes(s), key=lambda f: f.center().X)
cyl = lambda s: [f for f in s.faces() if f.geom_type.name == "CYLINDER"][0]
R = lambda c, k, r=None: {"c": c["id"], "k": k, "r": r}; fr = am.face_ref

def run(dx, with_conc=True):
    A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
    h = A.add_component("H", fixed=True); p = A.add_component("P", pos=(25, 3, 20)); p["rv"] = [0.05, 0.02, 0]
    m1 = A.add_mate("coincident", [R(h, "face", fr(top(parts["H"]))), R(p, "face", fr(bot(parts["P"])))]); A.prepare(m1)
    m2 = A.add_mate("distance", [R(h, "face", fr(sidex(parts["H"]))), R(p, "origin")]); A.prepare(m2); m2["value"] = 30 + dx
    m3 = None
    if with_conc:
        m3 = A.add_mate("concentric", [R(h, "face", fr(cyl(parts["H"]))), R(p, "face", fr(cyl(parts["P"])))]); A.prepare(m3)
    ok = A.solve()
    return A, p, ok, (m1, m2, m3)

# nothing in conflict: all three hold exactly
A, p, ok, ms = run(0.0)
assert ok and np.allclose(p["pos"], [20, 0, 25], atol=1e-4) and all(v == "ok" for v in A.status.values()), (ok, p["pos"], A.status)
# the distance mate is 0.5 / 3 mm away from the hole: the pin stays flat on the plate and where the distance says; only the concentric mate is flagged
for dx in (0.5, 3.0):
    A, p, ok, (m1, m2, m3) = run(dx)
    Rr, t = A.pose(p)
    assert not ok
    assert A.status[m1["id"]] == "ok", ("the plate contact moved", A.status, t)
    assert A.status[m2["id"]] == "ok", ("the distance moved", A.status, t)
    assert A.status[m3["id"]] == am.Assembly.CONFLICT, A.status[m3["id"]]
    assert abs(t[2] - 25) < 1e-4 and np.allclose(Rr[:, 2], [0, 0, 1], atol=1e-5), ("pin lifted or tilted", t, Rr[:, 2])
    assert abs(t[0] - (20 - dx)) < 1e-3, (t, dx)
# without the concentric mate the same two holding mates are fine (control)
A, p, ok, _ = run(3.0, with_conc=False)
assert A.status and all(v == "ok" for v in A.status.values())
print("OK concentric yields")
