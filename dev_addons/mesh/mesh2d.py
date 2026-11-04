"""The 2D side of a slice: a simplified outline as a sketch, a triangle mesh of it, and a DXF file of the outline.

    loops(poly)               -> [Nx2 arrays]: outer outline(s) first, then holes (closing point dropped)
    simplify(poly, tol)       -> polygon with no point moved more than tol
    mesh_polygon(poly, h)     -> (nodes (N,2), tris (M,3))  gmsh triangles of the region with element size about h
    write_dxf(poly, path)     -> LINE entities, one per outline segment (layer SKETCH)
"""
import numpy as np


def simplify(poly, tol):
    return poly.simplify(tol, preserve_topology=True) if tol > 0 else poly


def parts(poly):
    return [poly] if poly.geom_type == "Polygon" else list(poly.geoms)


def loops(poly):
    out, holes = [], []
    for g in parts(poly):
        out.append(np.asarray(g.exterior.coords)[:-1])
        holes += [np.asarray(r.coords)[:-1] for r in g.interiors]
    return out + holes


def mesh_polygon(poly, h):
    import gmsh
    if gmsh.isInitialized():
        gmsh.finalize()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("sketch")
        g = gmsh.model.geo

        def loop(xy):
            p = [g.addPoint(float(x), float(y), 0.0, h) for x, y in xy]
            ln = [g.addLine(p[i], p[(i + 1) % len(p)]) for i in range(len(p))]
            return g.addCurveLoop(ln)
        for part in parts(poly):
            rings = [loop(np.asarray(part.exterior.coords)[:-1])] + [loop(np.asarray(r.coords)[:-1]) for r in part.interiors]
            g.addPlaneSurface(rings)
        g.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", float(h))
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.mesh.generate(2)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        order = np.argsort(tags)
        xy = np.asarray(coords).reshape(-1, 3)[order][:, :2]
        remap = {int(t): i for i, t in enumerate(np.asarray(tags)[order])}
        et, _t, en = gmsh.model.mesh.getElements(2)
        if 2 not in list(et):
            raise RuntimeError("gmsh made no triangles for this outline")
        tri = np.asarray(en[list(et).index(2)], np.int64).reshape(-1, 3)
        return xy, np.vectorize(remap.get)(tri)
    finally:
        gmsh.finalize()


def stats(nodes, tris):
    p = nodes[tris]
    a, b, c = p[:, 0], p[:, 1], p[:, 2]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    e = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
    return {"nodes": int(len(nodes)), "triangles": int(len(tris)), "area": float(area.sum()), "edge_min": float(e.min()), "edge_max": float(e.max())}


def write_dxf(poly, path):
    rows = ["0", "SECTION", "2", "ENTITIES"]
    for ring in loops(poly):
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            rows += ["0", "LINE", "8", "SKETCH", "10", f"{a[0]:.6f}", "20", f"{a[1]:.6f}", "30", "0.0", "11", f"{b[0]:.6f}", "21", f"{b[1]:.6f}", "31", "0.0"]
    rows += ["0", "ENDSEC", "0", "EOF"]
    with open(path, "w") as f:
        f.write("\n".join(rows) + "\n")
