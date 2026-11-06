"""Distance between a pipe (cylinder axis / straight edge / circle edge) and a flat face: the axis is held parallel to the face at that distance."""
import faulthandler; faulthandler.dump_traceback_later(200, exit=True)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from build123d import Box, Cylinder, Pos, Rot
import asm_model as am
parts = {"B": Box(200, 200, 20), "T": Pos(0, 0, 0) * Rot(90, 0, 0) * Cylinder(10, 120)}
top = lambda s: max([f for f in s.faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().Z)
cyl = lambda s: [f for f in s.faces() if f.geom_type.name == "CYLINDER"][0]
R = lambda c, k, f: {"c": c["id"], "k": k, "r": am.face_ref(f)}
def make(fixed_box=True, order=0, tpos=(5, 7, 90), trv=(0.2, 0.1, 0.3), bpos=(0, 0, 0)):
    A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
    b = A.add_component("B", pos=bpos, fixed=fixed_box); t = A.add_component("T", pos=tpos, fixed=not fixed_box); 
    if fixed_box: t["rv"] = list(trv)
    else: b["rv"] = list(trv)
    refs = [R(b, "face", top(parts["B"])), R(t, "face", cyl(parts["T"]))]
    if order: refs.reverse()
    return A, b, t, refs
def gap(A, b, t):
    topf = A.world_entities({"type": "x", "refs": [R(b, "face", top(parts["B"])), R(t, "face", cyl(parts["T"]))]})
    pl, ax = topf
    return float(ax["d"] @ pl["n"]), float((ax["p"] - pl["p"]) @ pl["n"])
for order in (0, 1):
    for fixed_box in (True, False):
        A, b, t, refs = make(fixed_box, order)
        m = A.add_mate("distance", refs); A.prepare(m); m["value"] = 50.0
        assert A.solve(extra=[m]), (order, fixed_box, A.status)
        par, d = gap(A, b, t)
        assert abs(par) < 1e-6 and abs(abs(d) - 50.0) < 1e-4, (order, fixed_box, par, d)
# the default value is what it is now; the side is kept
A, b, t, refs = make(); t["rv"] = [0, 0, 0]
m = A.add_mate("distance", refs); A.prepare(m)
assert m["value"] > 0, m
side0 = np.sign(gap(A, b, t)[1]); A.solve(extra=[m]); assert np.sign(gap(A, b, t)[1]) == side0
# flip puts it on the other side of the face
m["value"] = 40.0
m["sgn"] = -m["sgn"]; assert A.solve(extra=[m]); assert np.sign(gap(A, b, t)[1]) == -side0 and abs(abs(gap(A, b, t)[1]) - 40) < 1e-4
# a circle edge: its centre keeps the distance (no parallel condition)
A, b, t, _ = make(); circ = [e for e in parts["T"].edges() if e.geom_type.name == "CIRCLE"][0]
m = A.add_mate("distance", [R(b, "face", top(parts["B"])), {"c": t["id"], "k": "edge", "r": am.edge_ref(circ)}]); A.prepare(m); m["value"] = 33.0
assert A.solve(extra=[m]), A.status
# without the exact first move the numeric fit still gets there from a near start
saved = dict(am.SNAPS); am.SNAPS.clear()
try:
    A, b, t, refs = make(tpos=(0, 0, 80), trv=(0.0, 0.0, 0.1))
    m = A.add_mate("distance", refs); A.prepare(m); m["value"] = 50.0
    assert A.solve(extra=[m]), A.status
    par, d = gap(A, b, t); assert abs(par) < 1e-5 and abs(abs(d) - 50) < 1e-3, (par, d)
finally:
    am.SNAPS.update(saved)
# stays held when the box is dragged (the pipe follows)
A, b, t, refs = make(); m = A.add_mate("distance", refs); A.prepare(m); m["value"] = 50.0; assert A.solve(extra=[m]); A.mates.append(m)
A.solve(); b["fixed"] = False
Rb, tb = A.pose(b)
for i in range(5):
    A.solve(drag={b["id"]: (Rb, tb + np.array([10.0 * (i + 1), 0, 0]))}, limit=A.cluster(b["id"]), grab={b["id"]: np.zeros(3)})
par, d = gap(A, b, t); assert abs(par) < 1e-4 and abs(abs(d) - 50) < 1e-3, (par, d)
print("PASS"); os._exit(0)
