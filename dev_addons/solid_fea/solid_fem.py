"""
solid_fem.py - meshing and the linear elastic solver of the 3D FEA add-on (no window).

  mesh_solid(geom, h, cancel, progress, opts)   gmsh fills the part (a STEP of it) with tetrahedra -> {"nodes", "tets", "faces": {face id: triangles}, "verts": {vertex id: node}}
                                    opts (see solid_mesh): minimum size, growth rate, refinement at curved surfaces, a smaller size on single faces, and the
                                    mesh type: tetrahedra, or hex-dominant (a block of hexahedra inside, tetrahedra and pyramids next to the surface: see
                                    solid_hexmesh; the mesh then also has "hexes" and "pyrs")
  quadratic(mesh)                   10-node tetrahedra (20-node hexahedra, 13-node pyramids) with straight edges (VTK node order); the triangles of every face get
                                    their mid-edge nodes
  linear(mesh)                      4-node tetrahedra (8-node hexahedra, 5-node pyramids): the same mesh without the mid-edge nodes
  solve(...)                        K u = f for a linear elastic isotropic material; supports and loads from the faces of the part
A mesh is a list of element GROUPS: q["groups"] = [{"kind": "tet" | "hex" | "pyr", "conn": (n, nodes per element)}]; q["conn"] is the tetrahedra's.

Units: mm, N, MPa (so a density of 7850 kg/m3 is 7.85e-9 t/mm3 and gravity 9810 mm/s2).
"""
import contextlib
import math
import os
import tempfile
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

import solid_elem as elem

EDGES = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]                      # VTK order of the mid-edge nodes of a 10-node tetrahedron
_A, _B = 0.5854101966249685, 0.1381966011250105
GAUSS = np.array([[_A, _B, _B, _B], [_B, _A, _B, _B], [_B, _B, _A, _B], [_B, _B, _B, _A]])         # 4 points, exact for degree 2
GW = np.full(4, 0.25)


class FemError(Exception):
    pass


class Cancelled(Exception):
    pass


DIRECT_LIMIT = 80000                 # the largest system that is solved directly (a factorisation); a larger one by preconditioned conjugate gradients


def _stage(progress, key, size=0.0):
    """Tell the progress bar (solid_progress.Tracker) that a stage of this kind begins.  `progress` may be any function of one text: then nothing happens."""
    fn = getattr(progress, "stage", None)
    if fn is not None:
        try:
            fn(key, size)
        except Exception:
            pass


def _part(progress, fraction):
    fn = getattr(progress, "part", None)
    if fn is not None:
        try:
            fn(fraction)
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------------------------------ mesh
@contextlib.contextmanager
def _session(geom, h, opts):
    """A gmsh model of the part with the sizes set: yields (gmsh, {surface tag: face id}); everything is cleaned up afterwards."""
    import gmsh
    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(geom["step"])
    if gmsh.isInitialized():
        gmsh.finalize()
    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("solid")
        gmsh.model.occ.importShapes(path)
        gmsh.model.occ.synchronize()
        if geom.get("solids"):                                         # an assembly: the faces the bodies share must be ONE surface (shared nodes)
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise FemError("gmsh found no solid in the part.")
        fmap = _match_surfaces(gmsh, geom)
        eff = element_sizes(geom, h, opts)                             # the size of every part (all the same size for a part, or for an assembly with one size)
        hmax, hlow = max(eff), min(eff)
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(hmax))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(opts.get("hmin") or 0.0) or float(hlow) / 6.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", float(opts.get("curv", 10)))
        gmsh.option.setNumber("Mesh.Optimize", 1)
        by_body = _body_fields(gmsh, geom, eff, float(h)) if (geom.get("solids") and len(set(eff)) > 1) else []
        if opts.get("size_map") is not None:                           # an adaptive mesh: the element size the last solution asks for (see solid_adapt)
            by_body = list(by_body) + [_size_map_field(gmsh, opts["size_map"])]
        _local_sizes(gmsh, fmap, opts.get("face_sizes") or [], float(hmax), float(opts.get("growth") or 1.3), by_body)
        yield gmsh, fmap
    finally:
        try:
            gmsh.clear()
            gmsh.finalize()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass


def _vertex_nodes(gmsh, geom, remap):
    verts = {}
    gv = np.asarray(geom["verts"], float)
    for (_d, tag) in gmsh.model.getEntities(0):
        nt, nc, _ = gmsh.model.mesh.getNodes(0, tag)
        if len(nt) and len(gv):
            p = np.asarray(nc, float).reshape(3)
            i = int(np.argmin(np.linalg.norm(gv - p, axis=1)))
            if np.linalg.norm(gv[i] - p) < 1e-6 * max(geom["diag"], 1.0) * 10:
                verts[i] = int(remap[int(nt[0])])
    return verts


def mesh_solid(geom, h, cancel=lambda: False, progress=lambda t: None, opts=None):
    """`opts`: None (the plain automatic mesh) or {"hmin": mm | 0, "growth", "curv": elements per full circle | 0,
    "face_sizes": [{"fids": [face ids], "h": mm}], "type": "tets" | "hexdom"} - see solid_mesh.resolve.
    A hex-dominant mesh that cannot be made (the part is too thin ...) is a mesh of tetrahedra with "hexdom_note" saying why."""
    opts = opts or {}
    if cancel():
        raise Cancelled()
    try:
        import solid_progress as spg
        _stage(progress, "meshhex" if opts.get("type") == "hexdom" else "mesh", opts.get("expect") or spg.estimate_for(geom, h, opts.get("body_h")))
    except Exception:
        pass
    if opts.get("type") == "hexdom" and geom.get("solids"):
        m = _mesh_tets(geom, h, cancel, progress, opts)
        m["hexdom_note"] = "An assembly is meshed with tetrahedra (hex-dominant meshing is for a single part)."
        return m
    if opts.get("type") == "hexdom":
        import solid_hexmesh as hm
        try:
            return _mesh_hexdom(geom, h, cancel, progress, opts, hm)
        except hm.NoHexes as ex:
            m = _mesh_tets(geom, h, cancel, progress, opts)
            m["hexdom_note"] = str(ex)
            return m
    return _mesh_tets(geom, h, cancel, progress, opts)


def _mesh_tets(geom, h, cancel, progress, opts):
    with _session(geom, h, opts) as (gmsh, fmap):
        progress("meshing")
        err = []
        done = False
        for alg in (1, 4, 10):
            try:
                gmsh.model.mesh.clear()
                gmsh.option.setNumber("Mesh.Algorithm3D", alg)
                gmsh.model.mesh.generate(3)
                done = True
                break
            except Exception as ex:
                err.append(str(ex))
        if not done:
            raise FemError("gmsh could not mesh the part: " + "; ".join(err))
        if cancel():
            raise Cancelled()
        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, np.int64)
        xyz = np.asarray(coords, float).reshape(-1, 3)
        remap = np.full(int(tags.max()) + 1, -1, np.int64)
        remap[tags] = np.arange(len(tags))
        tet_body = None
        if geom.get("solids"):
            tets, tet_body = _volume_tets(gmsh, geom, remap)
        else:
            _t, ent = gmsh.model.mesh.getElementsByType(4)
            tets = remap[np.asarray(ent, np.int64).reshape(-1, 4)]
        faces = {}
        for tag, fid in fmap.items():
            et, _et, en = gmsh.model.mesh.getElements(2, tag)
            if 2 in list(et):
                tri = remap[np.asarray(en[list(et).index(2)], np.int64).reshape(-1, 3)]
                faces[fid] = np.vstack([faces[fid], tri]) if fid in faces else tri
        verts = _vertex_nodes(gmsh, geom, remap)
    used, inv = np.unique(tets.ravel(), return_inverse=True)           # only nodes that belong to tetrahedra
    new = np.full(len(xyz), -1, np.int64)
    new[used] = np.arange(len(used))
    xyz = xyz[used]
    tets = inv.reshape(-1, 4)
    faces = {k: new[v] for k, v in faces.items()}
    faces = {k: v[(v >= 0).all(axis=1)] for k, v in faces.items()}
    verts = {k: int(new[v]) for k, v in verts.items() if new[v] >= 0}
    V = _signed_vol(xyz[tets])
    flip = V < 0
    tets[flip] = tets[flip][:, [0, 2, 1, 3]]
    if (np.abs(V) < 1e-14 * max(np.abs(V).max(), 1e-300)).any():
        keep = np.abs(V) >= 1e-14 * np.abs(V).max()
        tets = tets[keep]
        if tet_body is not None:
            tet_body = tet_body[keep]
    out = {"nodes": xyz, "tets": tets.astype(np.int64), "faces": faces, "verts": verts}
    if tet_body is not None:
        out["tet_body"] = tet_body.astype(np.int64)                    # the body of every tetrahedron; the tetrahedra are in the order of the bodies
    return out


def _volume_tets(gmsh, geom, remap):
    """(tetrahedra, body of each) of an assembly: the volumes of gmsh are matched to the pieces of the fused geometry (centre of mass and volume);
    the tetrahedra come out sorted by body."""
    pieces = geom["solids"]
    scale = max(geom["diag"], 1e-12)
    parts = []
    for (_d, tag) in gmsh.model.getEntities(3):
        best = _piece_of(gmsh, tag, pieces, scale)
        et, _et, en = gmsh.model.mesh.getElements(3, tag)
        if 4 in list(et):
            t = remap[np.asarray(en[list(et).index(4)], np.int64).reshape(-1, 4)]
            parts.append((pieces[best]["body"], t))
    if not parts:
        raise FemError("gmsh made no tetrahedra for the assembly.")
    parts.sort(key=lambda x: x[0])
    return np.vstack([t for _b, t in parts]), np.concatenate([np.full(len(t), b) for b, t in parts])


def _mesh_hexdom(geom, h, cancel, progress, opts, hm):
    """The surface (patch by patch, so the patch borders are mesh edges), then solid_hexmesh.build.  hm.NoHexes when it does not work out."""
    with _session(geom, h, opts) as (gmsh, fmap):
        progress("meshing the surface")
        try:
            gmsh.model.mesh.clear()
            gmsh.model.mesh.generate(2)
        except Exception as ex:
            raise FemError("gmsh could not mesh the surface of the part: " + str(ex))
        if cancel():
            raise Cancelled()
        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, np.int64)
        xyz = np.asarray(coords, float).reshape(-1, 3)
        remap = np.full(int(tags.max()) + 1, -1, np.int64)
        remap[tags] = np.arange(len(tags))
        tri, fid = [], []
        for (_d, tag) in gmsh.model.getEntities(2):
            et, _et, en = gmsh.model.mesh.getElements(2, tag)
            if 2 in list(et):
                t = remap[np.asarray(en[list(et).index(2)], np.int64).reshape(-1, 3)]
                tri.append(t)
                fid += [fmap.get(tag, -1)] * len(t)
        verts = _vertex_nodes(gmsh, geom, remap)
    if not tri:
        raise hm.NoHexes("The surface has no elements.")
    tri = np.vstack(tri)
    fid = np.asarray(fid)
    used = np.unique(tri)
    new = np.full(len(xyz), -1, np.int64)
    new[used] = np.arange(len(used))
    X, tri = xyz[used], new[tri]
    m = hm.build(X, tri, float(h), opts, cancel, progress)
    outer = m["outer"]
    faces = {}
    for f in np.unique(fid):
        if f >= 0:
            faces[int(f)] = outer[tri[fid == f]]
    verts = {k: int(outer[new[v]]) for k, v in verts.items() if new[v] >= 0}
    return {"nodes": m["nodes"], "tets": m["tets"], "hexes": m["hexes"], "pyrs": m["pyrs"], "faces": faces, "verts": verts, "hexdom": m["info"]}


def element_sizes(geom, h, opts=None):
    """[the element size (mm) of every body of an assembly] - `h` for the bodies that have no size of their own in opts["body_h"] ({body index: mm}) -
    or [h] for a single part."""
    nb = len(geom.get("bodies") or ())
    if not nb:
        return [float(h)]
    own = {int(k): float(v) for k, v in ((opts or {}).get("body_h") or {}).items()}
    return [float(own.get(i, h)) for i in range(nb)]


def _piece_of(gmsh, tag, pieces, scale):
    """The index of the piece of the fused assembly (geom["solids"]) that the gmsh volume `tag` is: nearest by centre of mass and volume."""
    c = np.array(gmsh.model.occ.getCenterOfMass(3, tag))
    v = gmsh.model.occ.getMass(3, tag)
    return min(range(len(pieces)), key=lambda k: np.linalg.norm(c - pieces[k]["center"]) / scale + abs(v - pieces[k]["volume"]) / max(pieces[k]["volume"], 1e-12))


def _body_fields(gmsh, geom, eff, h):
    """The element size of every part of an assembly, for gmsh: a field that is `eff[body]` on the volumes (and the faces, edges and points around them) of
    that body.  A face between two bodies belongs to both, so it gets the finer of the two sizes, and every part grows away from it: the mesh of the whole
    assembly stays ONE mesh, the nodes on a shared face stay shared.  -> the ids of the fields (to be minimised with the others)."""
    fld = gmsh.model.mesh.field
    pieces, scale = geom["solids"], max(geom["diag"], 1e-12)
    const = {}
    out = []
    for (_d, tag) in gmsh.model.getEntities(3):
        size = float(eff[pieces[_piece_of(gmsh, tag, pieces, scale)]["body"]]) if pieces else float(h)
        if size not in const:
            c = fld.add("MathEval")
            fld.setString(c, "F", repr(size))
            const[size] = c
        r = fld.add("Restrict")
        fld.setNumber(r, "InField", const[size])
        fld.setNumbers(r, "VolumesList", [tag])
        fld.setNumber(r, "IncludeBoundary", 1)
        out.append(r)
    return out


def _size_map_field(gmsh, m):
    """A gmsh size field from sizes at the nodes of an earlier mesh: m = {"xyz": (n, 3), "tets": (ne, 4) corner nodes, "size": (n,) mm}; the size inside
    an element is the linear interpolation of its four corners."""
    xyz, tets, size = np.asarray(m["xyz"], float), np.asarray(m["tets"], np.int64), np.asarray(m["size"], float)
    c, v = xyz[tets], size[tets]
    data = np.concatenate([c[:, :, 0], c[:, :, 1], c[:, :, 2], v], axis=1)                 # x1..x4 y1..y4 z1..z4 v1..v4 of every tetrahedron
    view = gmsh.view.add("size map")
    gmsh.view.addListData(view, "SS", len(tets), data.ravel().tolist())
    f = gmsh.model.mesh.field.add("PostView")
    gmsh.model.mesh.field.setNumber(f, "ViewTag", view)
    return f


def _local_sizes(gmsh, fmap, face_sizes, h, growth, extra=()):
    """A smaller element size on single faces: near such a face the size is `size`, and it grows to the global size `h` over the distance at which
    layers of elements, each `growth` times longer than the one before, have grown that far: (h - size) / (growth - 1).  `h` is the largest size of the
    model; the fields `extra` (the sizes of the parts of an assembly) are minimised with the face sizes."""
    if not face_sizes and not extra:
        return
    tag_of = {fid: tag for tag, fid in fmap.items()}
    fld = gmsh.model.mesh.field
    parts = list(extra)
    for item in face_sizes:
        tags = [tag_of[f] for f in item["fids"] if f in tag_of]
        hf = float(item["h"])
        if not tags or not hf < h:
            continue
        dist = fld.add("Distance")
        fld.setNumbers(dist, "SurfacesList", tags)
        fld.setNumber(dist, "Sampling", 40)
        thr = fld.add("Threshold")
        fld.setNumber(thr, "InField", dist)
        fld.setNumber(thr, "SizeMin", hf)
        fld.setNumber(thr, "SizeMax", h)
        fld.setNumber(thr, "DistMin", 0.0)
        fld.setNumber(thr, "DistMax", (h - hf) / max(growth - 1.0, 1e-6))
        parts.append(thr)
    if not parts:
        return
    low = fld.add("Min")
    fld.setNumbers(low, "FieldsList", parts)
    fld.setAsBackgroundMesh(low)


def _match_surfaces(gmsh, geom):
    """{gmsh surface tag: face id of the part}: the nearest face by centre of mass and area."""
    fm = {}
    used = set()
    cand = []
    for (_d, tag) in gmsh.model.getEntities(2):
        c = np.array(gmsh.model.occ.getCenterOfMass(2, tag))
        a = gmsh.model.occ.getMass(2, tag)
        for f in geom["faces"]:
            d = np.linalg.norm(c - f["center"]) / max(geom["diag"], 1e-12) + abs(a - f["area"]) / max(f["area"], 1e-12)
            cand.append((d, tag, f["id"]))
    for d, tag, fid in sorted(cand):
        if tag in fm or fid in used:
            continue
        if d > 0.05:
            continue
        fm[tag] = fid
        used.add(fid)
    return fm


def _signed_vol(c):
    return np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0


_EDGES = {"tet": EDGES, "hex": elem.HEX_EDGES, "pyr": elem.PYR_EDGES}


def _parts(mesh):
    """[(kind, corner connectivity)] of the elements of a mesh from mesh_solid: the tetrahedra, then the hexahedra, then the pyramids."""
    out = [("tet", mesh["tets"])]
    for kind, key in (("hex", "hexes"), ("pyr", "pyrs")):
        c = mesh.get(key)
        if c is not None and len(c):
            out.append((kind, np.asarray(c)))
    return out


def _by_body(groups, mesh):
    """The tetrahedra of an assembly in one group per body (they are in the order of the bodies, so the groups put together are the same list)."""
    tb = mesh.get("tet_body")
    if tb is None or not groups or groups[0]["kind"] != "tet":
        return groups
    conn = groups[0]["conn"]
    out = []
    for b in np.unique(tb):
        idx = np.where(tb == b)[0]
        out.append({"kind": "tet", "conn": conn[idx[0]:idx[-1] + 1], "body": int(b)})
    return out + groups[1:]


def view_cells(mesh):
    """The elements as VTK cells for the viewer (corner nodes only): {"cells", "types"}, or None for a mesh of tetrahedra only (those are drawn from "tets")."""
    parts = _parts(mesh)
    if len(parts) == 1:
        return None
    cells, types = [], []
    vt = {"tet": (4, 10), "hex": (8, 12), "pyr": (5, 14)}
    for kind, c in parts:
        k, t = vt[kind]
        cells.append(np.hstack([np.full((len(c), 1), k), c[:, :k]]).ravel())
        types.append(np.full(len(c), t, np.uint8))
    return {"cells": np.concatenate(cells).astype(np.int64), "types": np.concatenate(types)}


def quadratic(mesh):
    """Adds the mid-edge nodes: {"nodes", "conn" (the tetrahedra: ne, 10), "groups", "tri6": {face id: (k, 6)}, "vol", ...}."""
    nodes = mesh["nodes"]
    nn = len(nodes)
    key = lambda a, b: np.minimum(a, b).astype(np.int64) * nn + np.maximum(a, b)
    parts = _parts(mesh)
    keys = [np.stack([key(c[:, a], c[:, b]) for a, b in _EDGES[kind]], axis=1) for kind, c in parts]
    uniq, inv = np.unique(np.concatenate([k.ravel() for k in keys]), return_inverse=True)
    mid = 0.5 * (nodes[uniq // nn] + nodes[uniq % nn])
    groups = []
    pos = 0
    for (kind, c), kk in zip(parts, keys):
        ids = nn + inv[pos:pos + kk.size].reshape(kk.shape)
        pos += kk.size
        groups.append({"kind": kind, "conn": np.concatenate([c, ids], axis=1)})
    tetconn = groups[0]["conn"]
    groups = _by_body(groups, mesh)
    tri6 = {}
    for fid, tr in mesh["faces"].items():
        ms = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            k = key(tr[:, a], tr[:, b])
            p = np.searchsorted(uniq, k)
            ok = (p < len(uniq)) & (uniq[np.minimum(p, len(uniq) - 1)] == k)
            if not ok.all():
                raise FemError("A surface triangle is not an element face (the mesh is not conforming).")
            ms.append(nn + p)
        tri6[fid] = np.stack([tr[:, 0], tr[:, 1], tr[:, 2], ms[0], ms[1], ms[2]], axis=1)
    out = dict(mesh)
    out.update({"nodes": np.vstack([nodes, mid]), "conn": tetconn, "groups": groups, "tri6": tri6, "ftri": tri6, "order": 2,
                "viewcells": view_cells(mesh)})
    return out


def linear(mesh):
    """4-node tetrahedra (8-node hexahedra, 5-node pyramids): the corner nodes only.  "ftri" holds the corner nodes of the triangles of every face."""
    out = dict(mesh)
    groups = [{"kind": kind, "conn": np.asarray(c).copy()} for kind, c in _parts(mesh)]
    tetconn = groups[0]["conn"]
    groups = _by_body(groups, mesh)
    out.update({"conn": tetconn, "groups": groups, "ftri": {fid: np.asarray(tr).copy() for fid, tr in mesh["faces"].items()}, "order": 1,
                "viewcells": view_cells(mesh)})
    return out


def outward_normals(mesh, tri):
    """Unit outward normals and areas of surface triangles (corner node ids) from the tetrahedra next to them."""
    nodes, tets = mesh["nodes"], mesh["tets"]
    n = len(nodes)
    f = tets[:, [[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]]]                 # face i is opposite node i
    opp = np.repeat(tets[:, :, None], 1, axis=2)[:, :, 0]
    fs = np.sort(f, axis=2).reshape(-1, 3).astype(np.int64)
    fk = fs[:, 0] * n * n + fs[:, 1] * n + fs[:, 2]
    order = np.argsort(fk)
    fk = fk[order]
    tk = np.sort(tri, axis=1).astype(np.int64)
    tk = tk[:, 0] * n * n + tk[:, 1] * n + tk[:, 2]
    pos = np.clip(np.searchsorted(fk, tk), 0, len(fk) - 1)
    hit = fk[pos] == tk
    if not hit.all():
        raise FemError("A surface triangle has no tetrahedron behind it.")
    src = order[pos]
    opposite = tets[src // 4, src % 4]
    a, b, c = (nodes[tri[:, i]] for i in range(3))
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nv = cr / np.maximum(2 * area, 1e-300)[:, None]
    inward = np.einsum("ij,ij->i", nodes[opposite] - a, nv) > 0              # the opposite node lies on the inside: that side is not outward
    nv[inward] *= -1
    return nv, area


# ------------------------------------------------------------------------------------------------------------------------ elements
def _dNdL(L):
    """(10, 4): derivative of the 10 shape functions with respect to the 4 volume coordinates, at the point L."""
    d = np.zeros((10, 4))
    for i in range(4):
        d[i, i] = 4 * L[i] - 1
    for k, (a, b) in enumerate(EDGES):
        d[4 + k, a] = 4 * L[b]
        d[4 + k, b] = 4 * L[a]
    return d


def _N(L):
    n = np.zeros(10)
    for i in range(4):
        n[i] = L[i] * (2 * L[i] - 1)
    for k, (a, b) in enumerate(EDGES):
        n[4 + k] = 4 * L[a] * L[b]
    return n


def material_matrix(E, nu):
    c = E / ((1 + nu) * (1 - 2 * nu))
    D = np.zeros((6, 6))
    D[:3, :3] = c * nu
    for i in range(3):
        D[i, i] = c * (1 - nu)
    for i in range(3, 6):
        D[i, i] = c * (1 - 2 * nu) / 2
    return D


def _grad_L(nodes, conn, s, e):
    c = nodes[conn[s:e, :4]]
    A = np.ones((e - s, 4, 4))
    A[:, :, 1:] = c
    inv = np.linalg.inv(A)
    return np.transpose(inv[:, 1:, :], (0, 2, 1)), np.abs(_signed_vol(c))


def _rule(nne):
    """(derivatives of the shape functions at the integration points, weights, shape functions there) for 4-node (one point: constant strain, exact)
    and 10-node (four points) tetrahedra."""
    if nne == 4:
        return [np.eye(4)], np.array([1.0]), [np.full(4, 0.25)]
    return [_dNdL(L) for L in GAUSS], GW, [_N(L) for L in GAUSS]


_bmat = elem.bmat


def _as_groups(conn):
    """A list of groups from a list of groups or from the connectivity of tetrahedra."""
    return conn if isinstance(conn, (list, tuple)) else [{"kind": "tet", "conn": conn}]


def _edofs(conn):
    return (3 * conn[:, :, None] + np.arange(3)[None, None, :]).reshape(len(conn), 3 * conn.shape[1])


def _coo(Ke, ed, n):
    nd = ed.shape[1]
    return sp.coo_matrix((Ke.ravel(), (np.repeat(ed, nd, axis=1).ravel(), np.tile(ed, (1, nd)).ravel())), shape=(n, n)).tocsr()


def assemble(nodes, groups, E, nu, cancel=lambda: False, on_part=None):
    """The stiffness matrix of all the elements (`groups`: see the top of the file; or just the connectivity of tetrahedra) and the material matrix.
    on_part(fraction of the elements done) is called after every chunk of elements."""
    nn = len(nodes)
    D0 = D = material_matrix(E, nu)
    K = None
    groups = list(_as_groups(groups))
    total, done = max(sum(len(g["conn"]) for g in groups), 1), 0
    for g in groups:
        kind, conn = g["kind"], g["conn"]
        D = _group_D(g, D0)
        if kind == "tet":
            nne = conn.shape[1]
            dN, gw, _ns = _rule(nne)
            chunk = 4000
        else:
            chunk = 1500
        for s in range(0, len(conn), chunk):
            if cancel():
                raise Cancelled()
            e = min(s + chunk, len(conn))
            if kind == "tet":
                ndof = 3 * nne
                gL, V = _grad_L(nodes, conn, s, e)
                Ke = np.zeros((e - s, ndof, ndof))
                for d, w in zip(dN, gw):
                    B = _bmat(np.einsum("ik,ekx->eix", d, gL))
                    Ke += (w * V)[:, None, None] * (B.transpose(0, 2, 1) @ (D @ B))
                ed = _edofs(conn[s:e])
            else:
                hx = elem.as_hex(kind, conn[s:e])                                  # a pyramid as the collapsed hexahedron: the apex repeated
                try:
                    Ke = elem.stiffness(kind, nodes[hx], D)
                except elem.ElementError as ex:
                    raise FemError(str(ex))
                ed = _edofs(hx)
            part = _coo(Ke, ed, 3 * nn)
            K = part if K is None else K + part
            done += e - s
            if on_part is not None:
                on_part(done / total)
    return K, D0


def _group_D(g, D):
    """The material matrix of a group of elements: its own material g["mat"] = (E, nu) when it has one (a body of an assembly), else D."""
    m = g.get("mat")
    return material_matrix(float(m[0]), float(m[1])) if m else D


def stresses(nodes, groups, D, u):
    """Per element (the groups one after the other): von Mises at the integration points (max), the mean stress tensor, and the element volume."""
    groups = _as_groups(groups)
    ne = sum(len(g["conn"]) for g in groups)
    vm = np.zeros(ne)
    sig_mean = np.zeros((ne, 6))
    vol = np.zeros(ne)
    base = 0
    D0 = D
    for g in groups:
        kind, conn = g["kind"], g["conn"]
        D = _group_D(g, D0)
        if kind == "tet":
            nne = conn.shape[1]
            dN, _gw, _ns = _rule(nne)
            for s in range(0, len(conn), 8000):
                e = min(s + 8000, len(conn))
                gL, V = _grad_L(nodes, conn, s, e)
                vol[base + s:base + e] = V
                ue = u[_edofs(conn[s:e])]
                vmax = np.zeros(e - s)
                for d in dN:
                    B = _bmat(np.einsum("ik,ekx->eix", d, gL))
                    sg = np.einsum("eri,ei->er", B, ue) @ D.T
                    vmax = np.maximum(vmax, _vm(sg))
                    sig_mean[base + s:base + e] += sg / len(dN)
                vm[base + s:base + e] = vmax
        else:
            for s in range(0, len(conn), 3000):
                e = min(s + 3000, len(conn))
                hx = elem.as_hex(kind, conn[s:e])
                vmx, mean, vv = elem.recover(kind, nodes[hx], D, u[_edofs(hx)])
                vm[base + s:base + e], sig_mean[base + s:base + e], vol[base + s:base + e] = vmx, mean, vv
        base += len(conn)
    return vm, sig_mean, vol


def _vm(s):
    return np.sqrt(np.maximum(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2) + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2), 0))


def principal(sig):
    T = np.zeros((len(sig), 3, 3))
    T[:, 0, 0], T[:, 1, 1], T[:, 2, 2] = sig[:, 0], sig[:, 1], sig[:, 2]
    T[:, 0, 1] = T[:, 1, 0] = sig[:, 3]
    T[:, 1, 2] = T[:, 2, 1] = sig[:, 4]
    T[:, 0, 2] = T[:, 2, 0] = sig[:, 5]
    w = np.linalg.eigvalsh(T)
    return w[:, 2], w[:, 0]


def body_load(nodes, groups, b):
    """Consistent nodal forces of a uniform body force vector b (N/mm3); b may be a function of the group (a body of an assembly has its own density)."""
    f = np.zeros(3 * len(nodes))
    b0 = b
    for g in _as_groups(groups):
        kind, conn = g["kind"], g["conn"]
        b = b0(g) if callable(b0) else b0
        if kind == "tet":
            nne = conn.shape[1]
            _dn, gw, Ns = _rule(nne)
            for s in range(0, len(conn), 8000):
                e = min(s + 8000, len(conn))
                V = np.abs(_signed_vol(nodes[conn[s:e, :4]]))
                for n, w in zip(Ns, gw):
                    for i in range(nne):
                        for c in range(3):
                            np.add.at(f, 3 * conn[s:e, i] + c, w * V * n[i] * b[c])
        else:
            for s in range(0, len(conn), 3000):
                e = min(s + 3000, len(conn))
                hx = elem.as_hex(kind, conn[s:e])
                fe = elem.body_forces(kind, nodes[hx], b)
                f += np.bincount(_edofs(hx).ravel(), weights=fe.reshape(len(hx), -1).ravel(), minlength=len(f))
    return f


# ------------------------------------------------------------------------------------------------------------------------ the problem
def rigid_modes(xyz):
    """(n*3, 6) translations and rotations of points."""
    n = len(xyz)
    M = np.zeros((3 * n, 6))
    for c in range(3):
        M[c::3, c] = 1
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    M[1::3, 3], M[2::3, 3] = -z, y
    M[0::3, 4], M[2::3, 4] = z, -x
    M[0::3, 5], M[1::3, 5] = -y, x
    return M


def _rigid_check(nodes, rows):
    """Every rigid-body motion of the part must be stopped by the supports: rows = [(node, direction)] of the held directions."""
    nds = np.array(sorted({n for n, _ in rows}))
    pos = {int(n): i for i, n in enumerate(nds)}
    R = rigid_modes(nodes[nds])
    A = np.zeros((len(rows), 6))
    for r, (n, d) in enumerate(rows):
        i = pos[n]
        A[r] = d @ R[3 * i:3 * i + 3, :]
    sv = np.linalg.svd(A, compute_uv=False)
    if sv[-1] < 1e-9 * max(sv[0], 1e-300) or len(sv) < 6:
        raise FemError("The supports leave the part free to move or turn (a rigid-body motion is not stopped). Add or enlarge a support.")


def solve_system(Kff, ff, progress=None, cancel=None, extent=None):
    """Solves Kff x = ff: a direct solution up to DIRECT_LIMIT unknowns, else an incomplete-LU preconditioned CG.  Returns (x, 'direct' | 'iterative').
    progress / cancel / extent (the three sides of the bounding box of the part) only serve the progress bar: the stage that begins is announced, the
    iterative solver reports how far its residual has fallen, and a Cancel is noticed between iterations."""
    if len(ff) <= DIRECT_LIMIT:
        try:
            import solid_progress as spg
            _stage(progress, "factor", spg.factor_cost(len(ff), extent))
        except Exception:
            pass
        try:
            lu = spl.splu(Kff)
            return lu.solve(ff), "direct"
        except RuntimeError as ex:
            raise FemError(f"The system is singular ({ex}). Check the supports.")
    _stage(progress, "ilu", float(Kff.nnz))
    ilu = spl.spilu(Kff, drop_tol=1e-4, fill_factor=15)
    _stage(progress, "cg", float(len(ff)))
    b_norm = max(float(np.linalg.norm(ff)), 1e-300)
    seen = [0]

    def after_iteration(xk):                                  # the residual falls from |b| to 1e-9 |b|: the progress is how many of those nine decades are done
        seen[0] += 1
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None and seen[0] % 3 == 0:
            r = float(np.linalg.norm(Kff @ xk - ff)) / b_norm
            _part(progress, math.log10(1.0 / max(r, 1e-300)) / 9.0 if r < 1.0 else 0.0)
    uf, info = spl.cg(Kff, ff, rtol=1e-9, maxiter=3000, M=spl.LinearOperator(Kff.shape, ilu.solve), callback=after_iteration)
    if info != 0:
        raise FemError("The iterative solver did not converge. Use a larger element size.")
    return uf, "iterative"


def solve(q, E, nu, constraints, force, cancel=lambda: False, progress=lambda t: None):
    """q = quadratic mesh.  constraints: [(node array, direction (3,) or None for all three)]; force: (3 nn,) vector.
    Returns u (nn, 3), reactions per constraint, info."""
    nodes = q["nodes"]
    nn = len(nodes)
    progress("assembling")
    _stage(progress, "assemble", float(sum(len(g["conn"]) for g in _as_groups(q.get("groups") or q["conn"]))))
    K, D = assemble(nodes, q.get("groups") or q["conn"], E, nu, cancel, on_part=(lambda f: _part(progress, f)) if hasattr(progress, "part") else None)
    fixed = np.zeros(3 * nn, bool)
    pen = []
    rows = []                                                # (node, direction) pairs for the rigid-body check
    for nd, d in constraints:
        nd = np.unique(nd)
        if d is None:
            for c in range(3):
                fixed[3 * nd + c] = True
                e = np.zeros(3)
                e[c] = 1
                rows += [(int(n), e) for n in nd]
        else:
            d = np.asarray(d, float)
            d = d / np.linalg.norm(d)
            k = int(np.argmax(np.abs(d)))
            if abs(d[k]) > 0.999999:
                fixed[3 * nd + k] = True
            else:
                pen.append((nd, d))
            rows += [(int(n), d) for n in nd]
    if not rows:
        raise FemError("There is no support: the part is free to move.")
    _rigid_check(nodes, rows)
    if pen:
        kk = 1e8 * float(K.diagonal().mean())
        P = sp.lil_matrix((3 * nn, 3 * nn))
        for nd, d in pen:
            for n in nd:
                P[3 * n:3 * n + 3, 3 * n:3 * n + 3] += kk * np.outer(d, d)
        K = K + P.tocsr()
    free = np.where(~fixed)[0]
    progress(f"solving {len(free):,} unknowns")
    t0 = time.time()
    extent = np.ptp(np.asarray(nodes, float), axis=0).tolist()                 # the sides of the bounding box: what the progress bar's time estimate looks at
    Kff = K[free][:, free].tocsc()
    ff = force[free]
    if cancel():
        raise Cancelled()
    uf, how = solve_system(Kff, ff, progress=progress, cancel=cancel, extent=extent)
    u = np.zeros(3 * nn)
    u[free] = uf
    res = float(np.linalg.norm(Kff @ uf - ff) / max(np.linalg.norm(ff), 1e-300))
    if not np.isfinite(u).all() or res > 1e-6:
        raise FemError(f"The solution is not reliable (relative residual {res:.1e}). Check the supports: the part may be able to move freely.")
    r = K @ u - force
    reac = []
    allnodes = set()
    owner = {}                                   # a node held by several constraints (a support on a whole face and one on a patch of it, or two faces
    for ci, (nd, d) in enumerate(constraints):   # that share an edge) is counted for ONE of them: the strictest, and the later one among equals
        for n in np.unique(nd):
            key = (1 if d is None else 0, ci)
            if int(n) not in owner or key >= owner[int(n)]:
                owner[int(n)] = key
    for ci, (nd, d) in enumerate(constraints):
        nd = np.unique(nd)
        allnodes.update(int(n) for n in nd)
        mine = np.array([n for n in nd if owner[int(n)][1] == ci], dtype=int)
        if not len(mine):
            reac.append(np.zeros(3))
            continue
        idx = (3 * mine[:, None] + np.arange(3)[None, :]).ravel()
        rr = r[idx].reshape(-1, 3)
        if d is None:
            reac.append(rr.sum(axis=0))
        else:
            dd = np.asarray(d, float) / np.linalg.norm(d)
            reac.append((rr @ dd).sum() * dd)                       # a one-direction support only carries load along its direction
    an = np.array(sorted(allnodes))
    total = r[(3 * an[:, None] + np.arange(3)[None, :]).ravel()].reshape(-1, 3).sum(axis=0)
    info = {"total_reaction": total.tolist(), "solver": how, "residual": res, "seconds": time.time() - t0, "unknowns": int(len(free))}
    return u.reshape(-1, 3), np.array(reac), info, K, D
