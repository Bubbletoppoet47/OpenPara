"""The cutting plane of the slice window: how a plane is described and which 2D axes the sketch gets.  numpy only."""
import math

import numpy as np

STANDARD = {"XY plane (z = offset)": ((0.0, 0.0, 1.0), 1.0), "XZ plane (y = offset)": ((0.0, -1.0, 0.0), -1.0),
            "YZ plane (x = offset)": ((1.0, 0.0, 0.0), 1.0)}
# name -> (normal, factor): the plane is  n . x = factor * offset.   The normals are chosen so the sketch looks like the
# usual view of that plane: XY seen from +Z (x right, y up), XZ seen from the front (x right, z up), YZ seen from the right.


def unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n == 0:
        raise ValueError("The normal vector is zero.")
    return v / n


def frame(n, rot=0):
    """-> (u, v): the sketch X and Y axes as 3D unit vectors for a plane with unit normal n (u x v = n).
    v is as close to the model's +Z as the plane allows (or +Y for a horizontal plane); rot turns the sketch in 90 degree steps."""
    n = unit(n)
    ref = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.999 else np.array([0.0, 1.0, 0.0])
    v = ref - np.dot(ref, n) * n
    v /= np.linalg.norm(v)
    u = np.cross(v, n)
    for _ in range(int(rot) % 4):
        u, v = v, -u
    return u, v


def describe_frame(u, v):
    def name(a):
        i = int(np.argmax(np.abs(a)))
        if abs(a[i]) > 0.999:
            return ("+" if a[i] > 0 else "-") + "XYZ"[i]
        return "(%.2f, %.2f, %.2f)" % tuple(a)
    return f"Sketch X = model {name(u)}, sketch Y = model {name(v)}"


def plane_of(mode, offset_mm, point_mm, normal, flip=False, rot=0):
    """-> dict(n, d, u, v, o): the plane n.x = d, its sketch axes, and the sketch origin o (the model origin projected on the plane).
    mode is a key of STANDARD, or anything else for 'point + normal' (then point_mm and normal are used; offset moves the plane along n)."""
    if mode in STANDARD:
        n0, f = STANDARD[mode]
        n = unit(n0)
        d = f * offset_mm
    else:
        n = unit(normal)
        d = float(np.dot(n, np.asarray(point_mm, dtype=float))) + offset_mm
    if flip:
        n, d = -n, -d
    u, v = frame(n, rot)
    return {"n": n, "d": float(d), "u": u, "v": v, "o": n * d}
