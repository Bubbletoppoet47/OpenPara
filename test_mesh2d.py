"""The advanced mesh options of the 2D windows (sim_mesh2d, no window) and what the 2D mesher (physics_geom.mesh_faces, gmsh) does with them: a smaller size on an edge, a point or a
region, the minimum size, refinement at curved edges (exactly the number of elements around a circle that was asked for), the options that change nothing, the refusal of a target
that is gone, and the quality report against a mesh whose numbers are known."""
import math
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np

import physics_geom as pg
import sim_mesh2d as sm
import sketcher_core as sc


def ok(cond, msg):
    assert cond, msg
    print("ok:", msg)


# ---- 1. the options: defaults, completion, validation, what the mesher is given, the cache key, units
d = sm.default_mesh()
ok(d == {"advanced": False, "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 0, "local": []}, "the defaults are the plain automatic mesh")
ok(sm.complete(None) == d and sm.complete({"order": 1, "bogus": 5})["order"] == 1 and "bogus" not in sm.complete({"bogus": 5}), "a stored dict is completed and unknown keys are dropped")
c = sm.complete({"advanced": True, "local": [{"targets": [["ln", 3], ["pt", "5"]], "h": "2"}]})
ok(c["local"] == [{"targets": [("ln", 3), ("pt", 5)], "h": 2.0}], "targets that went through a JSON file (lists) are tuples again")
ok(sm.options(d) is None and sm.options({"advanced": True}) is None, "Advanced off, or on with nothing that changes the mesh: the plain mesh (no options)")
ok(sm.options({"advanced": False, "hmin": 1.0, "curv": 10}) is None, "the options are ignored while Advanced is off")
o = sm.options({"advanced": True, "hmin": 0.5, "curv": 12, "growth": 1.5, "local": [{"targets": [("ln", 4)], "h": 1.0}]})
ok(o == {"hmin": 0.5, "growth": 1.5, "curv": 12, "local": [{"targets": [("ln", 4)], "h": 1.0}]}, "the options the mesher is given")
ok(sm.order_of({"advanced": False, "order": 1}) == 2 and sm.order_of({"advanced": True, "order": 1}) == 1 and sm.order_of({"advanced": True}) == 2,
   "the order is linear only when Advanced is on and says so")
ok(sm.key_text(None) == "" and sm.key_text(o) != "" and sm.key_text(o) == sm.key_text(dict(o)), "the key text is empty for the plain mesh and stable")
o2 = sm.options({"advanced": True, "hmin": 0.5, "curv": 12, "growth": 1.5, "local": [{"targets": [("ln", 4)], "h": 2.0}]})
ok(sm.key_text(o) != sm.key_text(o2), "another local size is another key")
ok(sm.validate({"advanced": True, "hmin": 12.0}, 10.0) and "smaller than the element size" in sm.validate({"advanced": True, "hmin": 12.0}, 10.0), "a minimum size above the element size is refused")
ok("growth" in sm.validate({"growth": 5.0}, 10.0) and "growth" in sm.validate({"growth": 1.0}, 10.0), "a growth rate outside 1.05 to 3 is refused")
ok("circle" in sm.validate({"curv": 2}, 10.0) and sm.validate({"curv": 0}, 10.0) is None and sm.validate({"curv": 100}, 10.0) is None, "elements around a circle: 3 to 100, or off")
ok(sm.validate({"local": [{"targets": [("ln", 1)], "h": 0.0}]}, 10.0) and sm.validate({"local": [{"targets": [("ln", 1)], "h": 10.0}]}, 10.0), "a local size must be positive and smaller than the element size")
ok(sm.validate({"hmin": 3.0, "local": [{"targets": [("ln", 1)], "h": 2.0}]}, 10.0) is not None and sm.validate({"hmin": 1.0, "local": [{"targets": [("ln", 1)], "h": 2.0}]}, 10.0) is None,
   "a local size below the minimum size is refused")
u = sm.convert_lengths({"advanced": True, "hmin": 2.0, "local": [{"targets": [("ln", 1)], "h": 4.0}]}, 0.5)
ok(u["hmin"] == 1.0 and u["local"][0]["h"] == 2.0 and u["growth"] == 1.3, "a change of the unit system scales the lengths (and only them)")
ok(sm.target_text([("ln", 3), ("pt", 5), ("rg", 0)]) == "Line 3, Point 5, Region 1", "the targets are named in words")

# ---- 2. the mesher: a 100 x 20 plate
m = sc.Model()
p = [m.add_point(*c_) for c_ in ((0, 0), (100, 0), (100, 20), (0, 20))]
ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
g = pg.analyze(m)
inc = {f["id"] for f in g["faces"]}
plain = pg.mesh_faces(m, g, inc, 10.0)
again = pg.mesh_faces(m, g, inc, 10.0, opts=None)
ok(plain["stats"]["n_tris"] == again["stats"]["n_tris"] == 46 and np.allclose(plain["nodes"], again["nodes"]), f"no options: the plain mesh as it always was ({plain['stats']['n_tris']} triangles)")
LEFT = ls[3]
loc = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
ok(len(plain["curve_segs"][("ln", LEFT)]) == 2 and len(loc["curve_segs"][("ln", LEFT)]) >= 12, f"a size of 1.5 on the left edge: {len(loc['curve_segs'][('ln', LEFT)])} segments on it instead of 2")
P = loc["nodes"][loc["tris"]]
area = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1]) - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
cx = P[:, :, 0].mean(axis=1)
near, far = area[cx < 10].mean(), area[cx > 90].mean()
ok(near < 0.15 * far, f"the elements grow away from it: mean area {near:.2f} near the edge, {far:.1f} at the far end")
ok(loc["stats"]["edge_min"] < 1.6 and loc["stats"]["edge_max"] < 14.0, f"the smallest edge is about the local size ({loc['stats']['edge_min']:.2f}) and the rest stays near the global size ({loc['stats']['edge_max']:.1f})")
# the growth rate: a gentler growth makes more elements
slow = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.1, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
fast = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 2.0, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
ok(slow["stats"]["n_tris"] > loc["stats"]["n_tris"] > fast["stats"]["n_tris"], f"growth 1.1 / 1.3 / 2.0 make {slow['stats']['n_tris']} / {loc['stats']['n_tris']} / {fast['stats']['n_tris']} triangles")
pt = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("pt", p[0])], "h": 1.0}]})
Pn = pt["nodes"]
d0 = np.linalg.norm(Pn - np.array([0.0, 0.0]), axis=1)
ok(pt["stats"]["n_tris"] > 100 and 0 < np.sort(d0)[1] < 1.6, f"a size of 1 at a corner point: {pt['stats']['n_tris']} triangles, the nearest node is {np.sort(d0)[1]:.2f} away")
rg = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("rg", 0)], "h": 4.0}]})
ok(rg["stats"]["edge_max"] < 5.5 and rg["stats"]["n_tris"] > 5 * plain["stats"]["n_tris"], f"a size of 4 on the whole region: largest edge {rg['stats']['edge_max']:.2f}, {rg['stats']['n_tris']} triangles")
hm_free = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
hm_6 = pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 6.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
ok(hm_6["stats"]["edge_min"] > 2.5 * hm_free["stats"]["edge_min"] and hm_6["stats"]["n_tris"] < hm_free["stats"]["n_tris"],
   f"a minimum size of 6 stops the refinement: smallest edge {hm_6['stats']['edge_min']:.2f} instead of {hm_free['stats']['edge_min']:.2f}")
for bad in (("ln", 999), ("pt", 999), ("rg", 7)):
    try:
        pg.mesh_faces(m, g, inc, 10.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [bad], "h": 1.5}]})
        ok(False, f"{bad} is gone: refused")
    except pg.GeometryError as ex:
        ok("Local size 1" in str(ex), f"a target that is not there any more ({bad}) is refused: {ex}")
# local sizes and the adaptive loop together (the refine background and the local fields are one background mesh)
sizes = pg.node_sizes(plain["nodes"], plain["tris"]) * 0.5
both = pg.mesh_faces(m, g, inc, 10.0, refine={"nodes": plain["nodes"], "tris": plain["tris"], "sizes": sizes},
                     opts={"hmin": 0.0, "growth": 1.3, "curv": 0, "local": [{"targets": [("ln", LEFT)], "h": 1.5}]})
ok(both["stats"]["n_tris"] > plain["stats"]["n_tris"] and len(both["curve_segs"][("ln", LEFT)]) >= 12, "refinement from a previous mesh and a local size work together")

# ---- 3. refinement at curved edges: a 200 x 100 plate with a hole of radius 20
m2 = sc.Model()
q = [m2.add_point(*c_) for c_ in ((0, 0), (200, 0), (200, 100), (0, 100))]
for i in range(4):
    m2.add_line(q[i], q[(i + 1) % 4])
cid = m2.add_circle(m2.add_point(100, 50), 20)
g2 = pg.analyze(m2)
inc2 = {f["id"] for f in g2["faces"]}
a = pg.mesh_faces(m2, g2, inc2, 40.0)
for n in (24, 60):
    b = pg.mesh_faces(m2, g2, inc2, 40.0, opts={"hmin": 0.0, "growth": 1.3, "curv": n, "local": []})
    ok(len(b["curve_segs"][("ci", cid)]) == n, f"{n} elements around a full circle asked for: {len(b['curve_segs'][('ci', cid)])} on the hole (the plain mesh has {len(a['curve_segs'][('ci', cid)])})")
b24 = pg.mesh_faces(m2, g2, inc2, 40.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 24, "local": []})
ok(b24["stats"]["n_tris"] > 2.5 * a["stats"]["n_tris"], f"refining at the hole makes more triangles ({a['stats']['n_tris']} -> {b24['stats']['n_tris']})")
# an arc and a spline: the same, through the radius of curvature
m3 = sc.Model()
r_ = [m3.add_point(*c_) for c_ in ((0, 0), (100, 0), (100, 50), (0, 50))]
m3.add_line(r_[0], r_[1]); m3.add_line(r_[1], r_[2]); m3.add_line(r_[3], r_[0])
sp = m3.add_spline([r_[2], m3.add_point(70, 70), m3.add_point(30, 70), r_[3]]) if hasattr(m3, "add_spline") else None
if sp is not None:
    g3 = pg.analyze(m3)
    inc3 = {f["id"] for f in g3["faces"]}
    if inc3:
        s0 = pg.mesh_faces(m3, g3, inc3, 30.0)
        s1 = pg.mesh_faces(m3, g3, inc3, 30.0, opts={"hmin": 0.0, "growth": 1.3, "curv": 40, "local": []})
        ok(len(s1["curve_segs"][("sp", sp)]) > len(s0["curve_segs"][("sp", sp)]), f"a curved spline gets finer with the curvature refinement ({len(s0['curve_segs'][('sp', sp)])} -> {len(s1['curve_segs'][('sp', sp)])} segments)")

# ---- 4. the quality report against numbers that are known: right isosceles triangles with legs 1
nodes = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
tris = np.array([[0, 1, 2], [0, 2, 3]])
qr = sm.quality({"nodes": nodes, "tris": tris})
ok(abs(qr["ratio_min"] - 2 * ((2 - math.sqrt(2)) / 2) / (math.sqrt(2) / 2)) < 1e-12 and abs(qr["ratio_min"] - 0.8284271247) < 1e-9, f"radius ratio of a right isosceles triangle: {qr['ratio_min']:.6f}")
ok(abs(qr["angle_min"] - 45.0) < 1e-9 and abs(qr["angle_max"] - 90.0) < 1e-9 and qr["elements"] == 2 and qr["nodes"] == 4, "its angles are 45, 45 and 90 degrees")
ok(abs(qr["edge_min"] - 1.0) < 1e-12 and abs(qr["edge_max"] - math.sqrt(2)) < 1e-12 and abs(qr["area"] - 1.0) < 1e-12 and qr["inverted"] == 0, "edges 1 and sqrt 2, total area 1, nothing inverted")
ok(sm.verdict(qr) == "good", "that mesh is good")
eq = sm.quality({"nodes": np.array([[0.0, 0.0], [1.0, 0.0], [0.5, math.sqrt(3) / 2]]), "tris": np.array([[0, 1, 2]])})
ok(abs(eq["ratio_min"] - 1.0) < 1e-12 and abs(eq["angle_min"] - 60.0) < 1e-9, "an equilateral triangle has radius ratio 1 and 60 degree angles")
flat = sm.quality({"nodes": np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 0.01]]), "tris": np.array([[0, 1, 2]])})
ok(sm.verdict(flat) == "poor" and flat["ratio_min"] < 0.05 and flat["angle_max"] > 170, f"a flat triangle is poor (ratio {flat['ratio_min']:.3f}, largest angle {flat['angle_max']:.0f})")
inv = sm.quality({"nodes": nodes, "tris": np.array([[0, 2, 1], [0, 2, 3]])})
ok(inv["inverted"] == 1 and sm.verdict(inv) == "poor", "a clockwise triangle is counted as inverted")
real = sm.quality(a)
ok(abs(real["area"] - 20000.0) < 1e-6 and real["inverted"] == 0 and sm.verdict(real) == "good", f"the real mesh of the plate with a hole covers its {real['area']:.0f} area and is good (ratio {real['ratio_min']:.2f})")
print("OK mesh2d")
