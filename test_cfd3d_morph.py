"""The air mesh moved with the part (cfd3d_morph; no Qt): the volume of a tetrahedron, the Laplace stiffness, the movement of the nodes between the part and the box, the refusal of a mesh that
would be turned inside out, and the cancel.   python test_cfd3d_morph.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "dev_addons", "cfd3d"), os.path.join(HERE, "shared")]
import numpy as np
from scipy.spatial import Delaunay
import solid_fem as fem
import cfd3d_morph as mo

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


# ------------------------------------------------------------------------------------------------------------------- a mesh with known answers: random points in a cube of 10 mm, Delaunay
rng = np.random.default_rng(7)
corner = np.array([[x, y, z] for x in (0.0, 10.0) for y in (0.0, 10.0) for z in (0.0, 10.0)])
inner = rng.uniform(0.5, 9.5, (160, 3))
nodes = np.vstack([corner, inner])
tets = Delaunay(nodes).simplices.astype(np.int64)
V = mo.tet_volumes(nodes, tets)
tets[V < 0] = tets[V < 0][:, [0, 2, 1, 3]]                          # one orientation for all
V = mo.tet_volumes(nodes, tets)
hull = np.unique(Delaunay(nodes).convex_hull)
inside = np.setdiff1d(np.arange(len(nodes)), hull)

print("-- volumes and stiffness")
unit = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
ok(abs(mo.tet_volumes(unit, np.array([[0, 1, 2, 3]]))[0] - 1.0 / 6.0) < 1e-15, "the unit tetrahedron has the volume 1/6")
ok(mo.tet_volumes(unit, np.array([[0, 2, 1, 3]]))[0] < 0, "swapping two nodes turns the sign of the volume")
ok(abs(V.sum() - 1000.0) < 1e-6 and (V > 0).all(), f"the mesh fills the cube: {V.sum():.6f} mm3 of 1000 in {len(tets)} tetrahedra")
K = mo.stiffness(nodes, tets)
ok(abs(K - K.T).max() < 1e-12 * abs(K).max(), "the stiffness matrix is symmetric")
ok(np.abs(K @ np.ones(len(nodes))).max() < 1e-9, "a constant field costs nothing (every row adds up to zero)")
x = nodes[:, 0]
ok(abs(float(x @ (K @ x)) - len(tets)) < 1e-6 * len(tets), "every tetrahedron counts with the square of the gradient and not with its volume: the field x costs one per tetrahedron")
K2 = mo.stiffness(0.5 * nodes, tets)
ok(abs(K2.diagonal() / K.diagonal() - 4.0).max() < 1e-9, "the same mesh made half as small is four times as stiff: the small elements next to the part are the stiff ones")

print("-- the nodes between the part and the box")
D = np.tile([0.3, -0.2, 0.1], (len(hull), 1))
new = mo.morph(nodes, tets, hull, D, [])
ok(np.allclose(new - nodes, [0.3, -0.2, 0.1], atol=1e-10), "every node on the boundary moved by the same amount: every node moved by it")
new = mo.morph(nodes, tets, hull, np.tile([0.3, -0.2, 0.1], (len(hull), 1)), [])
ok(abs(mo.shrink(nodes, new, tets) - 1.0) < 1e-12, f"a movement of the whole mesh as one body shrinks nothing: {mo.shrink(nodes, new, tets):.6f}")
ok(abs(mo.shrink(nodes, nodes, tets) - 1.0) < 1e-15, "no movement, no shrink")

# a block of nodes in the middle (the part) moves; the box (the hull) stays
c = np.linalg.norm(nodes[inside] - 5.0, axis=1)
part = inside[c < 2.0]
D = np.tile([0.0, 0.5, 0.0], (len(part), 1))
new = mo.morph(nodes, tets, part, D, hull)
d = new - nodes
ok(np.allclose(d[part], D) and np.abs(d[hull]).max() == 0.0, "the part takes the movement it was given and the box stays")
rest = np.setdiff1d(np.arange(len(nodes)), np.concatenate([part, hull]))
ok(np.abs(d[rest, 1]).max() <= 0.5 + 1e-9 and np.abs(d[rest, 1]).min() >= -0.05, f"the nodes between them move between nothing and the part's movement ({d[rest, 1].min():.3f} to {d[rest, 1].max():.3f} mm)")
r = np.linalg.norm(nodes[rest] - 5.0, axis=1)
bands = [d[rest[(r >= lo) & (r < hi)], 1].mean() for lo, hi in ((0.0, 2.7), (2.7, 4.0), (4.0, 99.0))]
ok(bands[0] > bands[1] > bands[2] > 0, f"the further from the part, the less a node moves: {bands[0]:.3f}, {bands[1]:.3f}, {bands[2]:.3f} mm in three rings")
ok(abs(mo.shrink(nodes, new, tets) - np.min(mo.tet_volumes(new, tets) / V)) < 1e-15 and 0.5 < mo.shrink(nodes, new, tets) < 1.0, f"the worst shrink is the smallest volume ratio: {mo.shrink(nodes, new, tets):.4f}")
ok((mo.tet_volumes(new, tets) > 0).all(), "no tetrahedron is turned inside out")
twice = mo.morph(nodes, tets, part, 2.0 * D, hull)
ok(np.allclose(twice - nodes, 2.0 * d, atol=1e-10), "twice the movement of the part: twice the movement everywhere (it is linear)")
ok(np.allclose(mo.morph(nodes, tets, part, D * 0.0, hull), nodes), "nothing moved: the same mesh")

print("-- a movement the mesh cannot follow")
try:
    mo.morph(nodes, tets, part, np.tile([0.0, 9.0, 0.0], (len(part), 1)), hull)
    ok(False, "a movement through the box was not refused")
except fem.FemError as ex:
    ok("inside out" in str(ex) and "tetrahedra" in str(ex) and "larger box" in str(ex), f"a movement through the box is refused in words: '{str(ex)[:90]}...'")

print("-- cancel")
try:
    mo.morph(nodes, tets, part, D, hull, cancel=lambda: True)
    ok(False, "cancel was not honoured")
except fem.Cancelled:
    ok(True, "cancel stops the movement of the mesh")

print("\nFAILED:", FAILS) if FAILS else print("\nOK cfd3d morph")
sys.exit(1 if FAILS else 0)
