"""Solids from a closed triangle mesh.

    faceted_solid(mesh)          -> build123d Solid with one planar face per triangle (sewn).  Exact copy of the mesh; slow for large meshes
                                    (a few seconds per 10 000 triangles), so it refuses above `max_tris`.
    tet_mesh(mesh, size)         -> pyvista UnstructuredGrid of tetrahedra filling the mesh (gmsh); the mesh's own triangles are the boundary
    check(solid or grid, mesh)   -> volume difference to the mesh volume

No NURBS surfaces are fitted: that is a different (and much larger) problem.
"""
import numpy as np
import pyvista as pv

import repair as R


def mesh_volume(mesh):
    P, T = R.arrays(mesh)
    return abs(R.signed_volume(P, T))


def faceted_solid(mesh, max_tris=30000, tol=None):
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing)
    from OCP.gp import gp_Pnt
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from build123d import Solid

    P, T = R.arrays(mesh)
    if len(T) > max_tris:
        raise ValueError(f"{len(T)} triangles is too many for a faceted solid (limit {max_tris}). Reduce the mesh first.")
    d = R.diag_of(P)
    sew = BRepBuilderAPI_Sewing(1e-7 * d if tol is None else tol)
    pts = [gp_Pnt(float(x), float(y), float(z)) for x, y, z in P]
    for a, b, c in T:
        poly = BRepBuilderAPI_MakePolygon(pts[a], pts[b], pts[c], True)
        if not poly.IsDone():
            continue
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if face.IsDone():
            sew.Add(face.Face())
    sew.Perform()
    shape = sew.SewedShape()
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    if not ex.More():
        raise ValueError("Sewing produced no shell.")
    shell = TopoDS.Shell(ex.Current())
    ms = BRepBuilderAPI_MakeSolid(shell)
    fx = ShapeFix_Solid(ms.Solid())
    fx.Perform()
    s = Solid(fx.Solid())
    if s.volume < 0:
        s = Solid(fx.Solid().Reversed())
    return s


def tet_mesh(mesh, size=None, smooth_retry=True):
    """Tetrahedra inside a closed surface mesh.  size=None keeps the surface triangles as they are and fills the inside with tetrahedra
    of about their size; a number is the largest tetrahedron edge wanted."""
    import gmsh
    try:
        return _tet_mesh(mesh, size)
    except Exception as ex:
        if not smooth_retry:
            raise
        # a noisy surface that cuts through itself cannot be filled: smooth the copy a little and try again
        sm = R.to_mesh(*R.arrays(mesh)).smooth_taubin(n_iter=30, pass_band=0.1).extract_surface(algorithm=None).triangulate()
        g = _tet_mesh(sm, size)
        g.field_data["note"] = np.array([f"surface smoothed first ({str(ex)[:60]})"])
        return g


def _tet_mesh(mesh, size=None):
    import gmsh
    P, T = R.arrays(mesh)
    if gmsh.isInitialized():
        gmsh.finalize()                       # a failed run leaves gmsh in a state that spoils the next one
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("tets")
    s = gmsh.model.addDiscreteEntity(2)
    gmsh.model.mesh.addNodes(2, s, list(range(1, len(P) + 1)), P.ravel().tolist())
    gmsh.model.mesh.addElementsByType(s, 2, list(range(1, len(T) + 1)), (T + 1).ravel().tolist())
    gmsh.model.geo.addSurfaceLoop([s], 1)
    gmsh.model.geo.addVolume([1], 1)
    gmsh.model.geo.synchronize()
    if size:
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(size))
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)
    gmsh.model.mesh.generate(3)
    ntags, coords, _ = gmsh.model.mesh.getNodes()
    order = np.argsort(ntags)
    xyz = np.asarray(coords).reshape(-1, 3)[order]
    remap = {int(t): i for i, t in enumerate(np.asarray(ntags)[order])}
    et, _tags, en = gmsh.model.mesh.getElements(3)
    if 4 not in list(et):
        gmsh.clear()
        raise RuntimeError("gmsh made no tetrahedra (the surface cuts through itself)")
    tet = np.asarray(en[list(et).index(4)], np.int64).reshape(-1, 4)
    tet = np.vectorize(remap.get)(tet)
    gmsh.clear()
    cells = np.hstack([np.full((len(tet), 1), 4), tet]).ravel()
    return pv.UnstructuredGrid(cells, np.full(len(tet), pv.CellType.TETRA, np.uint8), xyz)


def tet_quality(grid):
    q = np.asarray(grid.cell_quality("scaled_jacobian")["scaled_jacobian"])
    return {"cells": int(grid.n_cells), "min_scaled_jacobian": float(q.min()), "p5": float(np.percentile(q, 5)),
            "inverted": int((q <= 0).sum()), "volume": float(grid.compute_cell_sizes()["Volume"].sum())}
