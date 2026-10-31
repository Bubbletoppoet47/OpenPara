"""exchange.py - STEP and STL files in and out.  No Qt.

    export_step(path, items, fuse=False)      items = [(name, solid)]: one solid named as given (a part), or several named solids in one file (an assembly)
    export_stl(path, shape, tol, ang)         a binary STL in mm
    export_stl_each(folder, items, tol, ang)  one numbered STL per item; returns the paths
    read_step(path)                           [(name, solid)] - one entry per solid in the file
    pack(shape) / unpack(text)                a shape as compact text (BREP, zlib, base64) so an imported body is saved inside the .gpd file
    place(shape, M)                           the shape moved by a 4 x 4 matrix (an assembly pose)
"""
import base64
import os
import re
import tempfile
import zlib

import numpy as np
from build123d import Compound, Location, Shape, export_brep, export_step as _export_step, export_stl as _export_stl, import_brep, import_step as _import_step
from OCP.gp import gp_Trsf


def place(shape, M):
    M = np.asarray(M, float)
    t = gp_Trsf()
    t.SetValues(M[0, 0], M[0, 1], M[0, 2], M[0, 3], M[1, 0], M[1, 1], M[1, 2], M[1, 3], M[2, 0], M[2, 1], M[2, 2], M[2, 3])
    return shape.moved(Location(t))


def safe(name):
    return re.sub(r'[<>:"/\\|?*]+', "_", str(name)).strip() or "part"


def _compound(items, fuse):
    items = [(n, s) for n, s in items if s is not None]
    if not items:
        raise ValueError("There is nothing to export (the part has no solid yet).")
    if len(items) == 1:
        n, s = items[0]
        out = Compound(list(s.solids()) or [s], label=safe(n))
        return out
    if fuse:
        acc = items[0][1]
        for _n, s in items[1:]:
            acc = acc + s
        return Compound(list(acc.solids()) or [acc], label="assembly")
    kids = []
    for n, s in items:
        sol = list(s.solids())
        if not sol:
            continue
        kids.append(Compound(children=[_named(x, f"{n}_{i}") for i, x in enumerate(sol, 1)], label=safe(n)) if len(sol) > 1 else _named(sol[0], n))
    return Compound(children=kids, label="assembly")


def _named(solid, name):
    solid = solid.moved(Location())
    solid.label = safe(name)
    return solid


def export_step(path, items, fuse=False):
    shape = _compound(items, fuse)
    if not _export_step(shape, str(path)):
        raise RuntimeError("the STEP writer reported a failure")
    return path


def _fresh(shape):
    """A copy without any triangulation: OpenCascade keeps a mesh made earlier (for the 3D view) if it is finer than the one asked for, so a coarser tolerance would be ignored."""
    from OCP.BRepTools import BRepTools
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    c = Shape.cast(BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape())
    BRepTools.Clean_s(c.wrapped)
    return c


def export_stl(path, shape, tol=0.02, ang=0.2):
    if shape is None:
        raise ValueError("There is nothing to export (the part has no solid yet).")
    shape = _fresh(shape)
    if not _export_stl(shape, str(path), tolerance=float(tol), angular_tolerance=float(ang)):
        raise RuntimeError("the STL writer reported a failure")
    return path


def export_stl_each(folder, items, tol=0.02, ang=0.2):
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, (n, s) in enumerate(items, 1):
        if s is None:
            continue
        p = os.path.join(folder, f"{i:02d}_{safe(n)}.stl")
        export_stl(p, s, tol, ang)
        out.append(p)
    if not out:
        raise ValueError("There is nothing to export.")
    return out


def read_step(path):
    root = _import_step(str(path))
    out = []

    def walk(shape, prefix):
        label = (getattr(shape, "label", "") or "").strip()
        sols = list(shape.solids()) if hasattr(shape, "solids") else []
        kids = list(getattr(shape, "children", []) or [])
        if kids and len(kids) > 0 and all(k is not shape for k in kids):
            for k in kids:
                walk(k, label or prefix)
            return
        for s in sols:
            out.append((label or prefix, s))
    walk(root, os.path.splitext(os.path.basename(str(path)))[0])
    if not out:
        out = [(os.path.splitext(os.path.basename(str(path)))[0], s) for s in root.solids()]
    if not out:
        raise ValueError("That STEP file holds no solids (only surfaces or curves).")
    names = {}
    res = []
    for n, s in out:                                        # unique names
        n = safe(n)
        names[n] = names.get(n, 0) + 1
        res.append((n if names[n] == 1 else f"{n}_{names[n]}", s))
    return res


def pack(shape):
    fd, p = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        export_brep(shape, p)
        raw = open(p, "rb").read()
    finally:
        os.remove(p)
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def unpack(text):
    fd, p = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    try:
        open(p, "wb").write(zlib.decompress(base64.b64decode(text)))
        return import_brep(p)
    finally:
        os.remove(p)
