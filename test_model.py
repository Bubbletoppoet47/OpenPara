import math
from pm_model import *
d = Document()
d.params = {"W": "40", "H": "W/2", "T": "10"}
s1 = d.add(new_feature("sketch", plane={"base": "Front"}, entities=[{"kind": "rect", "cx": 0, "cy": 0, "w": "W", "h": "H"}]))
e1 = d.add(new_feature("extrude", sketch=s1["id"], depth="T"))
d.rebuild(); print(d.status, round(d.solid.volume, 2)); assert abs(d.solid.volume - 40*20*10) < 1e-3
# sketch on the top face (the face with the largest +Z... find the face whose normal is toward the viewer side)
faces = d.solid.faces()
f = max(faces, key=lambda f: f.center().Z)
print("top face normal", f.normal_at())
s2 = d.add(new_feature("sketch", plane={"face": d.face_ref(f)}, entities=[{"kind": "circle", "cx": 0, "cy": 0, "d": "8"}]))
c1 = d.add(new_feature("cut", sketch=s2["id"], depth="0", through=True))
d.rebuild(); print(d.status, round(d.solid.volume, 2)); assert d.status[c1["id"]] == "ok", d.status
exp = 40*20*10 - math.pi*16*10 if False else None
print("volume after hole", d.solid.volume)
# fillet an edge
vert = [e for e in d.solid.edges() if e.geom_type.name == "LINE" and abs(e.tangent_at(0.5).Z) > 0.9]
fl = d.add(new_feature("fillet", size="2", edges=[d.edge_ref(vert[0])]))
d.rebuild(); print(d.status); assert d.status[fl["id"]] == "ok"
v0 = d.solid.volume; assert v0 < 6994.69, v0
# change a global: everything regenerates, hole and fillet follow
d.params["W"] = "60"; d.rebuild(); print(d.status, d.solid.volume, "was", v0); assert all(v == "ok" for v in d.status.values()) and abs(d.solid.volume - (60*30*10 - math.pi*16*30)) < 40, d.solid.volume
# rollback
d.rollback = 1; d.rebuild(); print("rollback", d.status); 
d.rollback = None
# error handling
d.params["T"] = "-3"; d.rebuild(); print(d.status)
d.params["T"] = "10"
# save/load
d2 = Document.from_json(d.to_json()); d2.rebuild(); print("reload ok", abs(d2.solid.volume - (d.rebuild() or d.solid.volume)) < 1e-6)
m = d.mesh(); print("mesh faces", len(m), "edges", len(d.edge_lines()), "sketch lines", len(d.sketch_lines(s2)))
# a rectangle drawn as four lines (closed loop) extrudes like a rectangle
d3 = Document()
L = [{"kind": "line", "x1": a, "y1": b, "x2": c, "y2": e} for a, b, c, e in ((0, 0, 30, 0), (30, 0, 30, 10), (30, 10, 0, 10), (0, 10, 0, 0))]
s3 = d3.add(new_feature("sketch", plane={"base": "Top"}, entities=L))
d3.add(new_feature("extrude", sketch=s3["id"], depth="5")); d3.rebuild(); print("lines ->", d3.status, d3.solid.volume)
assert abs(d3.solid.volume - 1500) < 1e-3
L[3]["y2"] = 4  # open chain -> no profile
d3.rebuild(); print("open chain:", d3.status)
print("OK")
