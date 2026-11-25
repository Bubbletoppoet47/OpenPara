"""coupled_surface.py: a field on a triangulated surface asked for at the nodes of another mesh of the same surface.   python test_coupled_surface.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COUPLED = next(p for p in (os.path.join(HERE, "addons_src", "coupled"), os.path.join(HERE, "dev_addons", "coupled")) if os.path.isdir(p))
sys.path[:0] = [HERE, COUPLED]
import numpy as np
import coupled_surface as cs

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def grid(n, shift=0.0, z=lambda x, y: 0.0 * x):
    """A square [0, 1]^2 cut into 2 n^2 triangles (the corner points moved by `shift` of a cell along the diagonal)."""
    x = np.linspace(0, 1, n + 1)
    X, Y = np.meshgrid(x, x, indexing="ij")
    X[1:-1, 1:-1] += shift / n
    Y[1:-1, 1:-1] += 0.6 * shift / n
    P = np.stack([X.ravel(), Y.ravel(), z(X, Y).ravel()], axis=1)
    idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    return P, np.vstack([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])


# a flat square: another mesh of it, a linear field comes out exactly
P1, T1 = grid(6)
P2, _T2 = grid(9, shift=0.3)
f = lambda P: 3.0 + 2.0 * P[:, 0] - 5.0 * P[:, 1]
loc = cs.SurfaceLocator(P1, T1)
v, info = loc.interpolate(f(P1), P2)
ok(np.abs(v - f(P2)).max() < 1e-12 and info["max_gap"] < 1e-12, f"a linear field of a flat surface is exact on another mesh of it: {np.abs(v - f(P2)).max():.1e}, gap {info['max_gap']:.1e}")
ok(v.min() >= f(P1).min() - 1e-12 and v.max() <= f(P1).max() + 1e-12, "nothing outside the range of the source can appear")
vv, _ = loc.interpolate(np.stack([f(P1), 2 * f(P1)], axis=1), P2)
ok(vv.shape == (len(P2), 2) and np.abs(vv[:, 1] - 2 * f(P2)).max() < 1e-12, "a vector field is handed over component by component")

# points off the surface report how far they are; points beyond the edge land on the edge
off = P2[:20] + np.array([0.0, 0.0, 0.07])
_v, info = loc.interpolate(f(P1), off)
ok(abs(info["max_gap"] - 0.07) < 1e-12, f"a point 0.07 above the surface reports the distance: {info['max_gap']:.4f}")
beyond, info = loc.interpolate(f(P1), np.array([[1.5, 0.5, 0.0], [-0.2, -0.2, 0.0]]))
ok(abs(info["max_gap"] - 0.5) < 1e-12 and abs(beyond[0] - f(np.array([[1.0, 0.5, 0.0]]))[0]) < 1e-12, f"a point beyond the edge takes the value of the nearest point of the edge: {beyond[0]:.4f}, gap {info['max_gap']:.3f}")

# a curved surface cut by two meshes: the field and the geometry both differ a little, and it is said so
bump = lambda x, y: 0.15 * np.sin(2.0 * x) * np.cos(1.5 * y)
Pc1, Tc1 = grid(14, z=bump)
Pc2, _ = grid(23, shift=0.4, z=bump)
g = lambda P: np.sin(3 * P[:, 0]) + P[:, 1] ** 2
lc = cs.SurfaceLocator(Pc1, Tc1)
vc, info = lc.interpolate(g(Pc1), Pc2)
ok(np.abs(vc - g(Pc2)).max() < 0.04, f"a smooth field on a curved surface is handed to another mesh to {np.abs(vc - g(Pc2)).max():.3f}")
ok(info["max_gap"] < 0.3 * lc.h and info["max_gap"] > 0, f"the two cuts of the curved surface lie {info['max_gap'] / lc.h:.2f} element sizes apart at most")

# far from the surface the gap is big
_v, far = lc.interpolate(g(Pc1), Pc2[:5] + np.array([0.0, 0.0, 2.0]))
ok(far["max_gap"] > 1.5, f"a point that belongs to no wall reports a large gap: {far['max_gap']:.2f}")

# a surface made of two separate walls: each point takes the value of its own wall
Pa, Ta = grid(4)
Pb = Pa + np.array([0.0, 0.0, 0.5])
Pall, Tall = np.vstack([Pa, Pb]), np.vstack([Ta, Ta + len(Pa)])
field = np.concatenate([np.full(len(Pa), 10.0), np.full(len(Pb), 20.0)])
la = cs.SurfaceLocator(Pall, Tall)
va, _ = la.interpolate(field, np.array([[0.3, 0.3, 0.01], [0.3, 0.3, 0.49]]))
ok(np.allclose(va, [10.0, 20.0]), f"two walls close together keep their own values: {va}")

# a field with the wrong length is refused in words
try:
    loc.interpolate(np.zeros(3), P2)
    ok(False, "a field of the wrong length is refused")
except ValueError as ex:
    ok("values" in str(ex), f"a field of the wrong length is refused: {ex}")
try:
    cs.SurfaceLocator(P1, np.zeros((0, 3), int))
    ok(False, "an empty surface is refused")
except ValueError as ex:
    ok("no triangle" in str(ex), f"an empty surface is refused: {ex}")

# the same triangles asked for twice are not searched twice (the answer is the same, and it comes from the memory)
n0 = loc._memo
a1 = loc.locate(P2)
b1 = loc.locate(P2.copy())
ok(a1 is b1, "the last search is remembered for the same points")
c1 = loc.locate(P2 + 1e-9)
ok(c1 is not a1, "and not for other points")

# the same part numbered the same way in two analyses
fa = [{"id": 0, "center": [0, 0, 0], "area": 2.0}, {"id": 1, "center": [10, 0, 0], "area": 3.0}, {"id": 2, "center": [0, 10, 0], "area": 1.0}]
fb = [dict(f) for f in fa]
ok(cs.same_faces(fa, fb, [0, 1, 2]) == (True, []), "the same faces are the same")
fb[1] = {"id": 1, "center": [10, 0.5, 0], "area": 3.0}
fb[2] = {"id": 2, "center": [0, 10, 0], "area": 1.2}
ok(cs.same_faces(fa, fb, [0, 1, 2]) == (False, [1, 2]), "a face that moved or changed its area is named")
ok(cs.same_faces(fa, fb[:2], [2]) == (False, [2]) and cs.same_faces(fa, fb, [0]) == (True, []), "a face missing in one of them is named; only the asked faces are compared")

print("\nFAILED:", FAILS) if FAILS else print("\nOK coupled surface")
sys.exit(1 if FAILS else 0)
