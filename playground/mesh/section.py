"""Cut a mesh with a plane and run the program's own 2D solvers on the cut.

    cut(mesh, origin, normal)              -> Section: the outline(s) of the cut as a polygon with holes, in the plane's own 2D axes
    to_model(section, tol)                 -> (sketch Model, {"lines": [(line id, (x1,y1), (x2,y2))]}) with the outline simplified to tol
    fea(section, mat, supports, loads, h)  -> the result dict of physics_fea.solve        (supports / loads pick outline lines by rule)
    cfd(section, setup, ...)               -> the result dict of physics_cfd.solve        (flow around the cut shape)

This is a 2D idealisation of the cut (plane stress / strain on the section, or flow past its outline); it is not a 3D analysis.
"""
import os
import sys

import numpy as np
import pyvista as pv

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))          # the program's own modules

import repair as R


class Section:
    def __init__(self, poly, origin, u, v, normal):
        self.poly, self.origin, self.u, self.v, self.normal = poly, np.asarray(origin, float), u, v, normal

    @property
    def area(self):
        return float(self.poly.area)

    def to3d(self, xy):
        xy = np.asarray(xy, float)
        return self.origin + xy[..., :1] * self.u + xy[..., 1:2] * self.v


def basis(normal):
    """2D axes of the cut plane: u is the world X axis (or Y when the plane is nearly perpendicular to X) projected into the plane, v = n x u,
    so a cut with normal Z reads as x, y and one with normal X reads as y, z."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    r = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = r - (r @ n) * n
    u /= np.linalg.norm(u)
    return u, np.cross(n, u), n


def cut(mesh, origin, normal, which="largest"):
    """Outline of the mesh where the plane (origin, normal) passes through it.  Nested loops become holes.  which: 'largest' keeps the
    biggest separate piece, 'all' keeps every piece as one multi-polygon."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import polygonize, unary_union
    u, v, n = basis(normal)
    sl = R.to_mesh(*R.arrays(mesh)).slice(normal=n, origin=origin)
    if sl.n_points == 0:
        raise ValueError("The plane does not cut the mesh.")
    lines = sl.lines.reshape(-1, 3)[:, 1:] if sl.n_lines else np.zeros((0, 2), int)
    pts = np.asarray(sl.points)
    o = np.asarray(origin, float)
    xy = np.stack([(pts - o) @ u, (pts - o) @ v], axis=1)
    from shapely.geometry import Polygon
    from shapely.ops import linemerge
    segs = [LineString([xy[a], xy[b]]) for a, b in lines if a != b]
    merged = linemerge(unary_union(MultiLineString(segs)))
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    loops = [Polygon(p.coords) for p in parts if p.is_closed and len(p.coords) >= 4]
    loops = [g.buffer(0) if not g.is_valid else g for g in loops]
    loops = [g for g in loops if g.area > 0]
    if not loops:
        raise ValueError("The cut is not a closed outline (the mesh is open there?). Repair the mesh first.")
    poly = loops[0]
    for r in loops[1:]:
        poly = poly.symmetric_difference(r)                       # filled loops, even-odd: a loop inside another one is a hole
    if poly.geom_type == "MultiPolygon":
        parts = sorted(poly.geoms, key=lambda g: -g.area)
        poly = parts[0] if which == "largest" else poly
    return Section(poly, o, u, v, n)


def to_model(sec, tol=None):
    """Sketch Model with the outline as points and straight lines (simplified so that no point moves more than tol)."""
    import sketcher_core as sc
    poly = sec.poly
    d = max(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1])
    tol = 0.003 * d if tol is None else tol
    poly = poly.simplify(tol, preserve_topology=True)
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    m = sc.Model()
    info = []
    for g in polys:
        for ring in [g.exterior] + list(g.interiors):
            xy = np.asarray(ring.coords)[:-1]
            ids = [m.add_point(x, y) for x, y in xy]
            for i in range(len(ids)):
                a, b = ids[i], ids[(i + 1) % len(ids)]
                info.append((m.add_line(a, b), tuple(xy[i]), tuple(xy[(i + 1) % len(ids)])))
    return m, {"lines": info, "size": d, "tol": tol, "n_lines": len(info)}


def select(info, rule):
    """Line targets whose middle satisfies rule(x, y) -> [("ln", id), ...]."""
    out = []
    for lid, a, b in info["lines"]:
        if rule(0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])):
            out.append(("ln", lid))
    return out


def mesh_2d(sec, h=None, tol=None):
    import physics_geom as pg
    m, info = to_model(sec, tol)
    geom = pg.analyze(m)
    if not geom["faces"]:
        raise ValueError("The outline has no closed region.")
    h = info["size"] / 40 if h is None else h
    mesh = pg.mesh_faces(m, geom, {f["id"] for f in geom["faces"]}, h)
    return m, geom, mesh, info


def fea(sec, mat, supports, loads, h=None, tol=None):
    """supports: [{"mode": "fixed"|"x"|"y", "where": rule(x, y)}], loads: [{"kind": "force", "fx", "fy", "where": rule} or
    {"kind": "pressure", "p", "where"} or {"kind": "traction", "tx", "ty", "where"}] - 'where' picks the outline lines.
    mat: {"E", "nu", "t" (thickness), "mode": "stress"|"strain", "order": 1|2}.  Units: mm, N, MPa."""
    import physics_fea as pf
    m, geom, mesh, info = mesh_2d(sec, h, tol)
    sup = [{"mode": s["mode"], "targets": select(info, s["where"])} for s in supports]
    lds = [dict({k: v for k, v in ld.items() if k != "where"}, targets=select(info, ld["where"])) for ld in loads]
    for s in sup + lds:
        if not s["targets"]:
            raise ValueError("A support or load rule matched no outline line.")
    mat = dict({"order": 2, "sy": 0.0, "su": 0.0, "eps_u": 0.1, "nl_on": False, "lin_on": True, "probes": [], "profile": None,
                "region_mats": None}, **mat)
    res = pf.solve(mesh, mat, sup, lds)
    res["_mesh_in"] = mesh
    res["_info"] = info
    return res


def cfd(sec, speed=0.2, rho=1.2, mu=1.8e-5, lscale=0.001, angle=0.0, steps=300, margins=None, h_body=None, h_far=None, tol=None, **extra):
    """Flow past the outline (laminar, 2D).  Units: the mesh is in `lscale` metres per unit (0.001 = mm); rho kg/m3, mu Pa s, speed m/s,
    angle in degrees (direction of the wind).  -> (result dict of physics_cfd.solve, mesh, info)."""
    import physics_cfd as pc
    import physics_geom as pg
    m, info = to_model(sec, tol)
    geom = pg.analyze(m)
    ids = [f["id"] for f in geom["faces"]]
    d = info["size"]
    h_body = d / 40 if h_body is None else h_body
    h_far = 6 * h_body if h_far is None else h_far
    margins = margins or (3.0, 6.0, 3.0, 3.0)                      # left, right, bottom, top - in body sizes
    mesh = pc.mesh_fluid(m, geom, ids, margins, h_body, h_far, 3.0)
    setup = {"lscale": lscale, "rho": rho, "mu": mu, "speed": speed, "angle": angle, "cfl": 0.5, "h_body": h_body, "max_steps": steps,
             "tol": 1e-5, "until": False, "ramp_steps": 20, "frame_every": max(1, steps // 5), "dt": None, "turb": False,
             "edge_geoms": {e["src"]: pc.edge_geometry(m, e) for e in geom["edges"]}}
    setup.update(extra)
    res = pc.solve(mesh, setup)
    return res, mesh, info
