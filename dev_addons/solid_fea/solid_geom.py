"""
solid_geom.py - the faces and vertices of a part for the 3D FEA add-on, with no window in it.

A face or a vertex is picked once and remembered as a SIGNATURE (where it is, which way it faces, how big it is).  After the part is rebuilt with other
parameters the signature is matched to the nearest face of the new part (position + normal), so supports and loads follow the geometry.
Units are those of the part (mm).
"""
import os
import tempfile

import numpy as np


class GeomError(Exception):
    pass


def analyze(solid):
    """{faces: [{id, kind, center, normal, area}], verts: [[x, y, z]], step: bytes, diag, volume, bbox, tess: [(V, T) per face]} of a build123d Solid."""
    import build123d as b
    if solid is None:
        raise GeomError("The part has no solid (it does not rebuild).")
    faces = []
    tess = []
    for i, f in enumerate(solid.faces()):
        c, n = f.center(b.CenterOf.MASS), f.normal_at()
        faces.append({"id": i, "kind": str(f.geom_type).split(".")[-1].lower(), "center": [c.X, c.Y, c.Z], "normal": [n.X, n.Y, n.Z], "area": float(f.area)})
    bb = solid.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    for f in solid.faces():
        v, t = f.tessellate(max(diag * 2e-3, 1e-6), 0.2)
        tess.append((np.array([[p.X, p.Y, p.Z] for p in v], float).reshape(-1, 3), np.array(t, int).reshape(-1, 3)))
    fd, p = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        b.export_step(solid, p)
        with open(p, "rb") as fh:
            step = fh.read()
    finally:
        try:
            os.remove(p)
        except OSError:
            pass
    verts = [[v.X, v.Y, v.Z] for v in solid.vertices()]
    return {"faces": faces, "verts": verts, "step": step, "diag": diag, "volume": float(solid.volume), "tess": tess,
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def face_sig(g, fid):
    f = g["faces"][fid]
    return {"type": "face", "kind": f["kind"], "center": list(f["center"]), "normal": list(f["normal"]), "area": f["area"]}


def vert_sig(g, vid):
    return {"type": "vertex", "point": list(g["verts"][vid])}


def match_face(g, sig, tol=0.6):
    """The id of the face of `g` that the signature means, or None.  Same kind of surface and a similar normal; the nearest centre wins."""
    best, bd = None, None
    d0 = max(g["diag"], 1e-12)
    n0 = np.asarray(sig["normal"], float)
    for f in g["faces"]:
        if f["kind"] != sig["kind"]:
            continue
        if float(np.dot(n0, f["normal"])) < 0.7 and sig["kind"] == "plane":
            continue
        dist = float(np.linalg.norm(np.asarray(f["center"]) - sig["center"])) / d0
        dist += 0.1 * abs(f["area"] - sig["area"]) / max(sig["area"], 1e-12) * (1 if dist > 0.02 else 0.2)
        if bd is None or dist < bd:
            best, bd = f["id"], dist
    return best if bd is not None and bd <= tol else None


def match_vertex(g, sig, tol=0.6):
    if not g["verts"]:
        return None
    d = np.linalg.norm(np.asarray(g["verts"]) - np.asarray(sig["point"]), axis=1) / max(g["diag"], 1e-12)
    i = int(np.argmin(d))
    return i if d[i] <= tol else None


def display_mesh(g):
    """One triangle mesh of all faces for the 3D view: (points, triangles, face id per triangle)."""
    P, T, F = [], [], []
    off = 0
    for i, (v, t) in enumerate(g["tess"]):
        if not len(t):
            continue
        P.append(v)
        T.append(t + off)
        F.append(np.full(len(t), i))
        off += len(v)
    if not P:
        return np.zeros((0, 3)), np.zeros((0, 3), int), np.zeros(0, int)
    return np.vstack(P), np.vstack(T), np.concatenate(F)
