"""cfd3d_mesh.py - the tetrahedral meshes of the fluid (gmsh): a straight channel, a round pipe, and the air around a part (a box with the part cut out).

Every mesher returns  {"nodes": (N, 3) in the unit of the geometry, "tets": (ne, 4) positively oriented, "patches": {name: (nt, 3) triangles of the
boundary}, "h": (the sizes it was asked for)}.  The boundary patches of the air around a part are the faces of the part (the integer ids of solid_geom)
and the six faces of the box, "x-", "x+", "y-", "y+", "z-", "z+" (the side the face is on).
"""
import contextlib
import os
import tempfile

import numpy as np

import solid_fem as fem

MeshError = fem.FemError
Cancelled = fem.Cancelled


def _stage(progress, key, size=0.0):
    fn = getattr(progress, "stage", None)
    if fn is not None:
        try:
            fn(key, size)
        except Exception:                                      # noqa: BLE001
            pass


@contextlib.contextmanager
def _gmsh():
    import gmsh
    if gmsh.isInitialized():
        gmsh.finalize()
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        yield gmsh
    finally:
        try:
            gmsh.clear()
            gmsh.finalize()
        except Exception:                                      # noqa: BLE001
            pass


def _generate(gmsh, cancel):
    """Meshes the current model with the first algorithm that works."""
    err = []
    for alg in (1, 4, 10):
        if cancel():
            raise Cancelled()
        try:
            gmsh.model.mesh.clear()
            gmsh.option.setNumber("Mesh.Algorithm3D", alg)
            gmsh.model.mesh.generate(3)
            return
        except Exception as ex:                                # noqa: BLE001
            err.append(str(ex))
    raise MeshError("gmsh could not mesh the fluid domain: " + "; ".join(err))


def _extract(gmsh, name_of):
    """The mesh of the current model; `name_of(surface tag)` is the patch name of a surface, or None for a surface that is not a boundary patch."""
    tags, coords, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(tags, np.int64)
    xyz = np.asarray(coords, float).reshape(-1, 3)
    remap = np.full(int(tags.max()) + 1, -1, np.int64)
    remap[tags] = np.arange(len(tags))
    _t, ent = gmsh.model.mesh.getElementsByType(4)
    tets = remap[np.asarray(ent, np.int64).reshape(-1, 4)]
    patches = {}
    for (_d, tag) in gmsh.model.getEntities(2):
        nm = name_of(tag)
        if nm is None:
            continue
        et, _x, en = gmsh.model.mesh.getElements(2, tag)
        if 2 in list(et):
            tri = remap[np.asarray(en[list(et).index(2)], np.int64).reshape(-1, 3)]
            patches[nm] = np.vstack([patches[nm], tri]) if nm in patches else tri
    used, inv = np.unique(tets.ravel(), return_inverse=True)              # only the nodes that belong to tetrahedra
    new = np.full(len(xyz), -1, np.int64)
    new[used] = np.arange(len(used))
    xyz = xyz[used]
    tets = inv.reshape(-1, 4)
    patches = {k: new[v] for k, v in patches.items()}
    patches = {k: v[(v >= 0).all(axis=1)] for k, v in patches.items()}
    c = xyz[tets]
    vol = np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    flip = vol < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    keep = np.abs(vol) > 1e-14 * np.abs(vol).max()
    return {"nodes": xyz, "tets": tets[keep].astype(np.int64), "patches": {k: v.astype(np.int64) for k, v in patches.items()}}


def _plane_name(gmsh, tag, lo, hi, tol):
    """"x-", "x+", ... when the surface lies in one of the six planes of the box lo..hi, else None."""
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, tag)
    mn, mx = (x0, y0, z0), (x1, y1, z1)
    for ax, c in enumerate("xyz"):
        if mx[ax] - mn[ax] < tol:
            if abs(mn[ax] - lo[ax]) < tol:
                return c + "-"
            if abs(mn[ax] - hi[ax]) < tol:
                return c + "+"
    return None


def _distance_sizes(gmsh, surfaces, h_near, h_far, growth, extra=()):
    """The element size grows from h_near at the surfaces to h_far, by `growth` per element (a background field).  `extra` = [(surfaces, size)]: faces with a
    size of their own (smaller than h_near), which grow to h_far the same way; the element size is the smallest the fields give."""
    fld = gmsh.model.mesh.field
    ids = []
    for tags, size in [(surfaces, h_near)] + [(t, s_) for t, s_ in extra]:
        if not len(tags):
            continue
        dist = fld.add("Distance")
        fld.setNumbers(dist, "SurfacesList", list(tags))
        fld.setNumber(dist, "Sampling", 40)
        thr = fld.add("Threshold")
        fld.setNumber(thr, "InField", dist)
        fld.setNumber(thr, "SizeMin", float(size))
        fld.setNumber(thr, "SizeMax", float(h_far))
        fld.setNumber(thr, "DistMin", 0.0)
        fld.setNumber(thr, "DistMax", max(h_far - size, 0.0) / max(growth - 1.0, 1e-6))
        ids.append(thr)
    if not ids:
        return
    bg = ids[0]
    if len(ids) > 1:
        bg = fld.add("Min")
        fld.setNumbers(bg, "FieldsList", ids)
    fld.setAsBackgroundMesh(bg)


def _sizes_off(gmsh, h_far, h_near):
    gmsh.option.setNumber("Mesh.MeshSizeMax", float(h_far))
    gmsh.option.setNumber("Mesh.MeshSizeMin", float(h_near) / 2.0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Optimize", 1)


# ------------------------------------------------------------------------------------------------------------------- the simple domains
def channel(L, W, H, h, hole=None, h_near=None, growth=1.25, cancel=lambda: False, progress=None):
    """A box 0..L x 0..W x 0..H with the flow along +x: patches "x-" (inlet), "x+" (outlet), "y-", "y+", "z-", "z+".
    `hole`: (cx, cy, cz, side) takes a cube out of it; its faces are the patches "b-x", "b+x", "b-y", "b+y", "b-z", "b+z"."""
    with _gmsh() as gmsh:
        gmsh.model.add("channel")
        box = gmsh.model.occ.addBox(0, 0, 0, L, W, H)
        if hole:
            cx, cy, cz, s = hole
            c = gmsh.model.occ.addBox(cx - s / 2, cy - s / 2, cz - s / 2, s, s, s)
            gmsh.model.occ.cut([(3, box)], [(3, c)])
        gmsh.model.occ.synchronize()
        tol = 1e-6 * max(L, W, H)
        names = {}
        body = []
        for (_d, tag) in gmsh.model.getEntities(2):
            nm = _plane_name(gmsh, tag, (0, 0, 0), (L, W, H), tol)
            if nm is None and hole:
                x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, tag)
                cx, cy, cz, s = hole
                for ax, c in enumerate("xyz"):
                    lo, hi = (x0, y0, z0)[ax], (x1, y1, z1)[ax]
                    if hi - lo < tol:
                        nm = "b-" + c if lo < (cx, cy, cz)[ax] else "b+" + c
                body.append(tag)
            names[tag] = nm
        hn = float(h_near or h)
        _sizes_off(gmsh, h, hn)
        if body and hn < h:
            _distance_sizes(gmsh, body, hn, h, growth)
        _generate(gmsh, cancel)
        out = _extract(gmsh, names.get)
    out["h"] = (hn, float(h))
    return out


def pipe(R, L, h, cancel=lambda: False, progress=None):
    """A round pipe of radius R and length L along +x: patches "inlet" (x = 0), "outlet" (x = L) and "wall"."""
    with _gmsh() as gmsh:
        gmsh.model.add("pipe")
        gmsh.model.occ.addCylinder(0, 0, 0, L, 0, 0, R)
        gmsh.model.occ.synchronize()
        names = {}
        tol = 1e-6 * L
        for (_d, tag) in gmsh.model.getEntities(2):
            x0, _y0, _z0, x1, _y1, _z1 = gmsh.model.getBoundingBox(2, tag)
            names[tag] = "inlet" if x1 < tol else ("outlet" if x0 > L - tol else "wall")
        _sizes_off(gmsh, h, h)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        _generate(gmsh, cancel)
        out = _extract(gmsh, names.get)
    out["h"] = (float(h), float(h))
    return out


# ------------------------------------------------------------------------------------------------------------------- the air around a part
def air_domain(geom, lo, hi, h_near, h_far, growth=1.3, cancel=lambda: False, progress=None, curv=0, hmin=0.0, face_sizes=None):
    """The box lo..hi (mm) with the part `geom` (solid_geom) cut out.  The patches are the faces of the part (their ids, matched to the faces of the
    geometry by position and area; a surface that cannot be matched is a patch named "s<number>", a wall like the others) and the six faces of the box.
    The element size is h_near on the part and grows to h_far by `growth` per element.  `curv` > 0: the surface elements follow a curved face with this
    many elements around a circle; `hmin` > 0: no element is smaller; `face_sizes` = [{"fids": [face ids], "h": mm}]: the faces with a size of their own."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    if not (hi > lo).all():
        raise MeshError("The fluid domain is empty: its box has no size along one of the axes.")
    bb = np.asarray(geom["bbox"], float)
    if (bb[0] < lo - 1e-9).any() or (bb[1] > hi + 1e-9).any():
        raise MeshError("The part sticks out of the fluid domain: make the box larger.")
    if not h_far >= h_near > 0:
        raise MeshError("The element size of the part must be positive and not larger than the one far away.")
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(geom["step"])
        with _gmsh() as gmsh:
            gmsh.model.add("air")
            parts = gmsh.model.occ.importShapes(path)
            gmsh.model.occ.synchronize()
            solids = [t for t in parts if t[0] == 3]
            if not solids:
                raise MeshError("gmsh found no solid in the part.")
            box = gmsh.model.occ.addBox(*lo, *(hi - lo))
            gmsh.model.occ.cut([(3, box)], solids, removeObject=True, removeTool=True)
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
            vols = gmsh.model.getEntities(3)
            if not vols:
                raise MeshError("The fluid domain could not be made (the part and the box do not make a volume).")
            tol = 1e-6 * float(np.linalg.norm(hi - lo))
            names, body = {}, []
            for (_d, tag) in gmsh.model.getEntities(2):
                nm = _plane_name(gmsh, tag, lo, hi, tol)
                if nm is None:
                    body.append(tag)
                names[tag] = nm
            fmap = _match_faces(gmsh, geom, body)
            for tag in body:
                names[tag] = int(fmap[tag]) if tag in fmap else f"s{tag}"
            by_face = {}
            for tag, fid in fmap.items():
                by_face.setdefault(int(fid), []).append(tag)
            extra = []
            for x in face_sizes or []:
                tags = [t for fid in x["fids"] for t in by_face.get(int(fid), [])]
                if tags and float(x["h"]) < h_near:
                    extra.append((tags, float(x["h"])))
            _stage(progress, "mesh", float(np.prod(hi - lo)) / float(h_far) ** 3 * 0.7)
            finest = min([h_near] + [s_ for _t, s_ in extra])
            _sizes_off(gmsh, h_far, finest)
            if hmin and hmin > 0:
                gmsh.option.setNumber("Mesh.MeshSizeMin", float(hmin))
            if curv and curv > 0:
                gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", float(curv))
            _distance_sizes(gmsh, body, h_near, h_far, growth, extra)
            _generate(gmsh, cancel)
            out = _extract(gmsh, names.get)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    out["h"] = (float(h_near), float(h_far))
    out["unmatched"] = sorted(n for n in out["patches"] if isinstance(n, str) and n.startswith("s"))
    return out


def _match_faces(gmsh, geom, tags):
    """{gmsh surface tag: face id of the part}: the nearest face by centre of mass and area (the same rule as solid_fem._match_surfaces, for the surfaces of
    the fluid domain that are not on the box)."""
    cand = []
    for tag in tags:
        c = np.array(gmsh.model.occ.getCenterOfMass(2, tag))
        a = gmsh.model.occ.getMass(2, tag)
        for f in geom["faces"]:
            d = np.linalg.norm(c - f["center"]) / max(geom["diag"], 1e-12) + abs(a - f["area"]) / max(f["area"], 1e-12)
            cand.append((d, tag, f["id"]))
    fm, used = {}, set()
    for d, tag, fid in sorted(cand):
        if tag in fm or fid in used or d > 0.05:
            continue
        fm[tag] = fid
        used.add(fid)
    return fm
