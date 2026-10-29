import numpy as np, math
from build123d import Box, Cylinder, Pos, Sphere
import asm_model as am
parts = {"A": Box(40, 40, 20), "B": Box(10, 10, 10), "H": Pos(0, 0, 0) * (Box(40, 40, 20) - Cylinder(5, 30)), "P": Cylinder(5, 30), "S": Sphere(6)}
A = am.Assembly(); A.solid_fn = lambda c: parts[c["path"]]
def face(solid, f): return am.face_ref(f)
def top(sol): return max([f for f in sol.faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().Z)
def bot(sol): return min([f for f in sol.faces() if f.geom_type.name == "PLANE"], key=lambda f: f.center().Z)
def side(sol, ax): return max([f for f in sol.faces() if f.geom_type.name == "PLANE"], key=lambda f: [f.center().X, f.center().Y][ax])
ca = A.add_component("A", fixed=True); cb = A.add_component("B", pos=(60, 30, 40)); cb["rv"] = [0.3, 0.2, 0.1]
R = lambda c, k, r=None: {"c": c["id"], "k": k, "r": r}
# 1) coincident: top of A with bottom of B
m = A.add_mate("coincident", [R(ca, "face", am.face_ref(top(parts["A"]))), R(cb, "face", am.face_ref(bot(parts["B"])))]); A.prepare(m)
ok = A.solve(); print("coincident ok", ok, A.status, "pos", np.round(cb["pos"], 3), "dof", A.dof)
Rr, t = A.pose(cb); assert abs(t[2] - 10 - 5) < 1e-4 and np.allclose(Rr[:, 2], [0, 0, 1], atol=1e-4), (t, Rr)
# 2) + distance in X (side faces): B's +X face to A's +X face = 3 mm inside? use distance between A right face and B right face
m2 = A.add_mate("distance", [R(ca, "face", am.face_ref(side(parts["A"], 0))), R(cb, "face", am.face_ref(side(parts["B"], 0)))], al="aligned"); A.prepare(m2); m2["value"] = 7.0; m2["al"] = "aligned"
ok = A.solve(); print("distance ok", ok, np.round(cb["pos"], 3), A.dof)
# 3) third mate: B's +Y side to A's +Y side distance 4 -> fully defined except rotation about z? parallels...
m3 = A.add_mate("distance", [R(ca, "face", am.face_ref(side(parts["A"], 1))), R(cb, "face", am.face_ref(side(parts["B"], 1)))]); A.prepare(m3); m3["value"] = 4.0; m3["al"] = "aligned"
ok = A.solve(); print("3 mates ok", ok, np.round(cb["pos"], 3), "dof", A.dof, A.status)
# conflicting mate
m4 = A.add_mate("distance", [R(ca, "face", am.face_ref(top(parts["A"]))), R(cb, "face", am.face_ref(bot(parts["B"])))]); A.prepare(m4); m4["value"] = 5.0
ok = A.solve(); print("conflict ok?", ok, A.status)
A.mates.remove(m4)
# concentric: hole H fixed, pin P
B = am.Assembly(); B.solid_fn = lambda c: parts[c["path"]]
ch = B.add_component("H", fixed=True); cp = B.add_component("P", pos=(30, 10, 5)); cp["rv"] = [0.2, 0.1, 0]
cyl = lambda sol: [f for f in sol.faces() if f.geom_type.name == "CYLINDER"][0]
m = B.add_mate("concentric", [R(ch, "face", am.face_ref(cyl(parts["H"]))), R(cp, "face", am.face_ref(cyl(parts["P"])))]); B.prepare(m)
ok = B.solve(); print("concentric", ok, np.round(cp["pos"], 3), "dof", B.dof)
assert abs(cp["pos"][0]) < 1e-4 and abs(cp["pos"][1]) < 1e-4
# + coincident P bottom to H top -> only spin about axis left
m = B.add_mate("coincident", [R(ch, "face", am.face_ref(top(parts["H"]))), R(cp, "face", am.face_ref(bot(parts["P"])))]); B.prepare(m)
ok = B.solve(); print("pin on top", ok, np.round(cp["pos"], 3), "dof", B.dof)
# tangent: sphere on plane, cylinder on plane
C = am.Assembly(); C.solid_fn = lambda c: parts[c["path"]]
c1 = C.add_component("A", fixed=True); c2 = C.add_component("S", pos=(5, 3, 30))
sph = lambda sol: sol.faces()[0]
m = C.add_mate("tangent", [R(c1, "face", am.face_ref(top(parts["A"]))), R(c2, "face", am.face_ref(sph(parts["S"])))]); C.prepare(m)
ok = C.solve(); print("sphere tangent", ok, np.round(c2["pos"], 3), C.dof); assert abs(c2["pos"][2] - 16) < 1e-4
c3 = C.add_component("P", pos=(0, 0, 40)); c3["rv"] = [0.4, 0.3, 0.2]
m = C.add_mate("tangent", [R(c1, "face", am.face_ref(top(parts["A"]))), R(c3, "face", am.face_ref(cyl(parts["P"])))]); C.prepare(m)
ok = C.solve(); print("cylinder on plane", ok, np.round(c3["pos"], 3), np.round(A.pose(c3)[0] if False else am.rodrigues(c3["rv"])[:, 2], 3), C.dof)
assert abs(c3["pos"][2] - 15) < 1e-3
# straight edge tangent to a cylinder: edge of B (a vertical edge) with the pin P lying
lin = lambda sol: [e for e in sol.edges() if e.geom_type.name == "LINE"][0]
# lock + json
L = am.Assembly(); L.solid_fn = lambda c: parts[c["path"]]
l1 = L.add_component("A", fixed=True); l2 = L.add_component("B", pos=(50, 0, 0)); l2["rv"] = [0, 0, 0.5]
m = L.add_mate("lock", [R(l1, "origin"), R(l2, "origin")]); L.prepare(m)
l2["pos"] = [10, 10, 10]; l2["rv"] = [0.4, 0, 0]; ok = L.solve(); print("lock", ok, np.round(l2["pos"], 3), np.round(l2["rv"], 3))
assert np.allclose(l2["pos"], [50, 0, 0], atol=1e-4)
L2 = am.Assembly.from_json(L.to_json()); assert L2.mates[0]["type"] == "lock"
# symmetric points about the Front plane? use origin planes: B at x=20 and S at x=-20 about Right plane
D = am.Assembly(); D.solid_fn = lambda c: parts[c["path"]]
d0 = D.add_component("A", fixed=True); d1 = D.add_component("B", pos=(20, 0, 0), fixed=True); d2 = D.add_component("B", pos=(-5, 8, 3))
m = D.add_mate("symmetric", [R(d1, "origin"), R(d2, "origin"), {"c": d0["id"], "k": "plane", "r": {"n": "Right"}}]); D.prepare(m)
ok = D.solve(); print("symmetric", ok, np.round(d2["pos"], 3), D.dof)
assert abs(d2["pos"][0] + 20) < 1e-4 and abs(d2["pos"][1]) < 1e-3
# drag with mates: B on A top, drag far in x -> stays on plane
ok = A.solve(drag={cb["id"]: (am.rodrigues(cb["rv"]), np.array([cb["pos"][0] + 5, cb["pos"][1] - 6, cb["pos"][2] + 9]))}, weight=0.05)
print("drag", ok, np.round(cb["pos"], 3), A.dof)
print("OK")
