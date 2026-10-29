"""pose_math.py - the rotation math of the 3D assembly (numpy only; no program modules, so the solver core can use it).

A pose is [tx, ty, tz, rx, ry, rz]: millimetres and degrees, R = Rz*Ry*Rx, a point q of the part is at R q + t.
FRAMES: the standard views as (u, v, n): the sketch's x axis, y axis and the direction to the viewer, in the assembly's axes."""
import math

import numpy as np

FRAMES = {
    "Front":  ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
    "Back":   ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    "Right":  ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    "Left":   ((0, -1, 0), (0, 0, 1), (-1, 0, 0)),
    "Top":    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "Bottom": ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
}


def axis_matrix(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    x, y, z = a
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


def euler_matrix(rx, ry, rz):
    return axis_matrix((0, 0, 1), rz) @ axis_matrix((0, 1, 0), ry) @ axis_matrix((1, 0, 0), rx)


def matrix_euler(R):
    """(rx, ry, rz) in degrees with R = Rz(rz) Ry(ry) Rx(rx); ry within [-90, 90]."""
    s = max(-1.0, min(1.0, -float(R[2, 0])))
    ry = math.asin(s)
    if abs(s) > 1 - 1e-9:                                  # looking straight along an axis: rx and rz are not separate, put it all in rx
        rz = 0.0
        rx = math.atan2(R[0, 1], R[1, 1]) if s > 0 else math.atan2(-R[0, 1], R[1, 1])
    else:
        rx = math.atan2(R[2, 1], R[2, 2])
        rz = math.atan2(R[1, 0], R[0, 0])
    return [math.degrees(rx), math.degrees(ry), math.degrees(rz)]


def rotation(pose):
    return euler_matrix(pose[3], pose[4], pose[5])


def rotvec_matrix(w):
    """Rotation matrix of the rotation vector w (radians, axis * angle)."""
    w = np.asarray(w, float)
    th = float(np.linalg.norm(w))
    if th < 1e-14:
        return np.eye(3) + _skew(w)
    k = w / th
    K = _skew(k)
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)


def matrix_rotvec(R):
    """Rotation vector (radians) of a rotation matrix."""
    c = (float(np.trace(R)) - 1.0) / 2.0
    c = max(-1.0, min(1.0, c))
    th = math.acos(c)
    if th < 1e-12:
        return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / 2.0
    if abs(th - math.pi) < 1e-6:                           # half a turn: the axis comes from R + I
        M = (R + np.eye(3)) / 2.0
        i = int(np.argmax(np.diag(M)))
        k = M[:, i] / math.sqrt(max(M[i, i], 1e-30))
        return k / np.linalg.norm(k) * th
    k = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2.0 * math.sin(th))
    return k * th


def _skew(w):
    return np.array([[0.0, -w[2], w[1]], [w[2], 0.0, -w[0]], [-w[1], w[0], 0.0]])


def apply_delta(pose, delta):
    """The pose moved by delta = [dtx, dty, dtz, wx, wy, wz] (mm, radians): translated, and rotated by the rotation vector w about the
    part's origin (left-multiplied, i.e. about the assembly's axes)."""
    R = rotvec_matrix(delta[3:6]) @ rotation(pose)
    return [pose[0] + delta[0], pose[1] + delta[1], pose[2] + delta[2]] + matrix_euler(R)


def project(pose, q, view):
    """(u, v) in mm of the part point q seen from view."""
    u, v, _n = FRAMES[view]
    P = rotation(pose) @ np.asarray(q, float) + np.asarray(pose[:3], float)
    return float(P @ np.asarray(u, float)), float(P @ np.asarray(v, float))
