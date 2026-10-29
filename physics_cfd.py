"""
Physics Calc - CFD: 2D incompressible Navier-Stokes by finite elements on a gmsh triangle mesh (per unit depth).

  * Taylor-Hood elements: quadratic (6-node) velocity, linear (3-node) pressure - the standard stable pair
  * the mesh is the gmsh mesh; the mid-edge velocity nodes are added here, with straight element sides
  * backward-Euler time marching, convection linearised with the previous step (Oseen), streamline-diffusion stabilisation
  * one direct sparse solve per step; nothing is averaged or smoothed, the converged state is the last time step
  * inflow = a speed and an angle: box sides facing the wind are inlets, the opposite sides are outlets (traction-free,
    pressure 0); a side the wind runs exactly along is a free-slip wall
  * solid bodies = closed loops of the sketch, no-slip walls
  * optional turbulence: k-omega SST (Menter 2003), wall-resolved (no wall functions), solved after each flow step on the same
    mesh with linear elements; the momentum equation then uses nu + nu_t with the full stress form

Units: the sketch lengths are converted with `lscale` (metres per sketch unit); everything inside is SI.
Pressure is the gauge pressure relative to the outlet (kinematic pressure * rho).  Forces and pressures are per metre of depth.
"""
import math
import time
import warnings

import numpy as np

import physics_geom as pg
import physics_solve as psolve


class Cancelled(Exception):
    pass


class ModelError(Exception):
    pass


LENGTH_UNITS = {"mm": 1.0e-3, "cm": 1.0e-2, "m": 1.0, "in": 0.0254, "ft": 0.3048}
FLUIDS = {"Air 15 C (sea level)": (1.225, 1.789e-5), "Air 20 C": (1.204, 1.825e-5),
          "Water 20 C": (998.2, 1.002e-3), "Custom": (None, None)}
SIDES = ("bottom", "right", "top", "left")
SIDE_NORMAL = {"bottom": (0.0, -1.0), "right": (1.0, 0.0), "top": (0.0, 1.0), "left": (-1.0, 0.0)}


# ----------------------------------------------------------------------------------------------
# bodies
# ----------------------------------------------------------------------------------------------
def body_faces(geom):
    """Faces that can be solid bodies: the ones that are not nested inside another outline."""
    return [f for f in geom["faces"] if f["depth"] == 0]


def body_loops(geom, faces):
    """Outline of the union of the chosen faces (outer boundaries only) as closed loops of half-edges (edge index, +1 / -1).
    An edge shared by two chosen faces is inside the solid and is dropped."""
    edges = geom["edges"]
    present = {}
    for f in faces:
        for h in f["cycle"]:
            present[h] = present.get(h, 0) + 1
    keep = [h for h in present if (h[0], -h[1]) not in present]

    def start(h):
        e = edges[h[0]]
        return e["a"] if h[1] == 1 else e["b"]

    def end(h):
        e = edges[h[0]]
        return e["b"] if h[1] == 1 else e["a"]

    loops = [[h] for h in keep if edges[h[0]]["kind"] == "ci"]
    by_start = {}
    for h in keep:
        if edges[h[0]]["kind"] != "ci":
            by_start.setdefault(start(h), []).append(h)
    used = set()
    for h0 in keep:
        if edges[h0[0]]["kind"] == "ci" or h0 in used:
            continue
        loop, cur = [], h0
        while True:
            used.add(cur)
            loop.append(cur)
            if end(cur) == start(h0):
                break
            nxt = [x for x in by_start.get(end(cur), []) if x not in used]
            if not nxt:
                break
            cur = nxt[0]
        if end(loop[-1]) != start(loop[0]):
            raise pg.GeometryError("The outline of the chosen bodies is not a closed loop (a body touches another one in a way "
                                   "that cannot be traced). Check the sketch near edge " +
                                   f"{edges[loop[0][0]]['src'][0]} {edges[loop[0][0]]['src'][1]}.")
        loops.append(loop)
    return loops


# ----------------------------------------------------------------------------------------------
# the mesh of the fluid (gmsh)
# ----------------------------------------------------------------------------------------------
def convex_corners(m, geom, loops, min_turn_deg=20.0):
    """Sharp convex corners of the body outline (where the flow has to turn round the body).
    -> [(point id, turn angle in degrees)].  Smooth joins (tangent arcs) and concave corners are not listed."""
    edges = geom["edges"]
    out = []
    for loop in loops:
        if len(loop) < 2:
            continue
        seq = []                                    # points of every half-edge, in travel direction
        for k, d in loop:
            p = pg.edge_pts(m, edges[k])
            seq.append(p if d == 1 else p[::-1])
        pts = [q for p in seq for q in p]
        area = 0.0
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            area += x0 * y1 - x1 * y0
        sgn = 1.0 if area >= 0 else -1.0            # +1: loop runs counter-clockwise (the body is on its left)
        for i, (k, d) in enumerate(loop):
            e = edges[k]
            pid = e["a"] if d == 1 else e["b"]      # start point of this half-edge
            prev, cur = seq[i - 1], seq[i]
            v0 = (prev[-1][0] - prev[-2][0], prev[-1][1] - prev[-2][1])
            v1 = (cur[1][0] - cur[0][0], cur[1][1] - cur[0][1])
            if math.hypot(*v0) < 1e-12 or math.hypot(*v1) < 1e-12:
                continue
            turn = math.degrees(math.atan2(v0[0] * v1[1] - v0[1] * v1[0], v0[0] * v1[0] + v0[1] * v1[1])) * sgn
            if turn >= min_turn_deg:
                out.append((pid, turn))
    return out


def mesh_fluid_once(m, geom, face_ids, margins, h_body, h_far, transition, progress=None, cancel=None, algorithm=6, bl=None,
                    refine=None, use_corners=True):
    """Triangles for the box around the bodies, minus the bodies.
    margins = (left, right, bottom, top) in multiples of the body size.  h_body / h_far = element size at the walls / far away
    (sketch units), `transition` = distance (in body sizes) over which the size grows.
    -> mesh dict: nodes (N,2) sketch units, tris (M,3) counter-clockwise, wall_segs {(kind,id): [(na, nb)]},
       box_segs {side: [(na, nb)]}, box, size, stats.
    bl = None, or {"h1", "ratio", "thickness"} (sketch units): a wall-resolved boundary-layer mesh (triangles, stretched along the walls).
    refine = None, or {"nodes", "tris", "sizes", "floor"}: adaptive refinement - the element size wanted at each node of a previous mesh
    (never below `floor`); the new mesh follows it wherever it is smaller than the normal sizes."""
    import gmsh
    pg.face_geometry_ok(geom)
    faces = [f for f in geom["faces"] if f["id"] in face_ids and f["depth"] == 0]
    if not faces:
        raise pg.GeometryError("No body is switched on.")
    if h_body <= 0 or h_far <= 0:
        raise pg.GeometryError("The element sizes must be positive.")
    if h_body > h_far:
        raise pg.GeometryError("The element size at the body must not be larger than the size far away.")

    def tick(txt, f):
        if cancel and cancel():
            raise pg.Cancelled()
        if progress:
            progress(txt, f)

    loops = body_loops(geom, faces)
    xs = [p[0] for f in faces for p in f["poly"]]
    ys = [p[1] for f in faces for p in f["poly"]]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    size = max(xmax - xmin, ymax - ymin)
    ml, mr, mb, mt = margins
    if min(margins) < 0 or size <= 0:
        raise pg.GeometryError("The domain margins must not be negative.")
    bx0, bx1 = xmin - ml * size, xmax + mr * size
    by0, by1 = ymin - mb * size, ymax + mt * size
    est = (bx1 - bx0) * (by1 - by0) / (0.43 * h_far * h_far)
    if est > 1.5e6:
        raise pg.GeometryError(f"That would be about {est:.2g} elements even far from the body - increase the far element size "
                               "or reduce the margins.")
    edges = geom["edges"]
    used = sorted({k for loop in loops for k, _ in loop})

    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("cfd")
        tick("Building the geometry", 0.05)
        pt_tag = {}
        next_extra = [1000000]

        def gpoint(x, y, pid=None, hh=None):
            hh = h_body if hh is None else hh
            if pid is not None:
                if pid not in pt_tag:
                    pt_tag[pid] = gmsh.model.geo.addPoint(x, y, 0.0, hh, pid + 1)
                return pt_tag[pid]
            next_extra[0] += 1
            return gmsh.model.geo.addPoint(x, y, 0.0, hh, next_extra[0])

        next_curve = [0]

        def gcurve(fn, *a):
            next_curve[0] += 1
            return fn(*a, next_curve[0])

        curve_tag = {}
        for k in used:
            e = edges[k]
            if e["kind"] == "ln":
                pa, pb = m.pts[e["a"]], m.pts[e["b"]]
                curve_tag[k] = [gcurve(gmsh.model.geo.addLine, gpoint(pa[0], pa[1], e["a"]), gpoint(pb[0], pb[1], e["b"]))]
            elif e["kind"] == "ar":
                c = m.pts[e["c"]]
                a0, a1, r = pg.arc_angles(m, e)
                n = max(1, int(math.ceil((a1 - a0) / (0.9 * math.pi))))
                ids = [gpoint(*m.pts[e["a"]], e["a"])]
                for i in range(1, n):
                    ang = a0 + (a1 - a0) * i / n
                    ids.append(gpoint(c[0] + r * math.cos(ang), c[1] + r * math.sin(ang)))
                ids.append(gpoint(*m.pts[e["b"]], e["b"]))
                cc = gpoint(c[0], c[1], e["c"])
                curve_tag[k] = [gcurve(gmsh.model.geo.addCircleArc, ids[i], cc, ids[i + 1]) for i in range(n)]
            else:
                c, r = m.pts[e["c"]], e["r"]
                cc = gpoint(c[0], c[1], e["c"])
                ids = [gpoint(c[0] + r * math.cos(i * math.pi / 2), c[1] + r * math.sin(i * math.pi / 2)) for i in range(4)]
                curve_tag[k] = [gcurve(gmsh.model.geo.addCircleArc, ids[i], cc, ids[(i + 1) % 4]) for i in range(4)]

        def loop_tags(cycle):
            tags = []
            for k, d in cycle:
                seg = curve_tag[k]
                tags += list(seg) if d == 1 else [-t for t in reversed(seg)]
            return tags

        corners = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
        cp = [gmsh.model.geo.addPoint(x, y, 0.0, h_far, 3000001 + i) for i, (x, y) in enumerate(corners)]
        box_curve = {}
        for i, side in enumerate(SIDES):                      # bottom, right, top, left - counter-clockwise
            box_curve[side] = gcurve(gmsh.model.geo.addLine, cp[i], cp[(i + 1) % 4])
        box_loop = gmsh.model.geo.addCurveLoop([box_curve[s] for s in SIDES])
        hole_loops = []
        for loop in loops:
            rev = [(k, -d) for k, d in reversed(loop)]        # a hole in the fluid is traversed clockwise
            hole_loops.append(gmsh.model.geo.addCurveLoop(loop_tags(rev)))
        surf = gmsh.model.geo.addPlaneSurface([box_loop] + hole_loops)
        gmsh.model.geo.synchronize()

        body_curves = [t for k in used for t in curve_tag[k]]
        fd = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(fd, "CurvesList", body_curves)
        for opt in ("Sampling", "NumPointsPerCurve"):
            try:
                gmsh.model.mesh.field.setNumber(fd, opt, 200)
                break
            except Exception:
                continue
        ft = gmsh.model.mesh.field.add("Threshold")
        dmin = 2.0 * h_body
        dmax = max(transition * size, dmin + h_far)
        gmsh.model.mesh.field.setNumber(ft, "InField", fd)
        gmsh.model.mesh.field.setNumber(ft, "SizeMin", h_body)
        gmsh.model.mesh.field.setNumber(ft, "SizeMax", h_far)
        gmsh.model.mesh.field.setNumber(ft, "DistMin", dmin)
        gmsh.model.mesh.field.setNumber(ft, "DistMax", dmax)
        corner_list = convex_corners(m, geom, loops) if use_corners else []
        corner_tags = [pt_tag[pid] for pid, _ in corner_list if pid in pt_tag]
        if bl:
            fb = gmsh.model.mesh.field.add("BoundaryLayer")
            gmsh.model.mesh.field.setNumbers(fb, "CurvesList", body_curves)
            gmsh.model.mesh.field.setNumber(fb, "Size", bl["h1"])
            gmsh.model.mesh.field.setNumber(fb, "Ratio", bl["ratio"])
            gmsh.model.mesh.field.setNumber(fb, "Thickness", bl["thickness"])
            gmsh.model.mesh.field.setNumber(fb, "Quads", 0)
            if corner_list:
                tags_f = [pt_tag[pid] for pid, _ in corner_list if pid in pt_tag]
                sizes_f = [int(min(12, max(3, round(t / 15.0)))) for pid, t in corner_list if pid in pt_tag]
                gmsh.model.mesh.field.setNumbers(fb, "FanPointsList", tags_f)
                gmsh.model.mesh.field.setNumbers(fb, "FanPointsSizesList", sizes_f)
            gmsh.model.mesh.field.setAsBoundaryLayer(fb)
        h_corner = 0.5 * h_body
        base_fields = [ft]
        if corner_tags:
            fcd = gmsh.model.mesh.field.add("Distance")
            gmsh.model.mesh.field.setNumbers(fcd, "PointsList", corner_tags)
            fct = gmsh.model.mesh.field.add("Threshold")
            gmsh.model.mesh.field.setNumber(fct, "InField", fcd)
            gmsh.model.mesh.field.setNumber(fct, "SizeMin", h_corner)
            gmsh.model.mesh.field.setNumber(fct, "SizeMax", h_far)
            gmsh.model.mesh.field.setNumber(fct, "DistMin", 1.0 * h_body)
            gmsh.model.mesh.field.setNumber(fct, "DistMax", max(8.0 * h_body, 2.0 * dmin))
            base_fields.append(fct)
        if len(base_fields) > 1:
            bg = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(bg, "FieldsList", base_fields)
        else:
            bg = ft
        if refine:
            pg.background_from_sizes(gmsh, refine, others=[bg])
        else:
            gmsh.model.mesh.field.setAsBackgroundMesh(bg)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        size_min = 0.5 * min(bl["h1"] if bl else h_body, h_corner if corner_tags else 1e300)
        if refine:
            size_min = min(size_min, float(refine.get("floor", size_min)))
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_min)
        gmsh.option.setNumber("Mesh.MeshSizeMax", h_far)
        gmsh.option.setNumber("Mesh.Smoothing", 5)
        gmsh.option.setNumber("Mesh.Algorithm", algorithm)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.RecombineAll", 0)
        tick("Meshing (gmsh)", 0.2)
        gmsh.model.mesh.generate(2)
        tick("Reading the mesh", 0.8)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, dtype=np.int64)
        coords = np.asarray(coords, dtype=float).reshape(-1, 3)
        index = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
        index[tags] = np.arange(len(tags))
        types, _, enodes = gmsh.model.mesh.getElements(2, surf)
        tri_list = []
        for t, nodes in zip(types, enodes):
            if t != 2:
                raise pg.GeometryError("gmsh produced elements other than 3-node triangles.")
            tri_list.append(index[np.asarray(nodes, dtype=np.int64)].reshape(-1, 3))
        if not tri_list:
            raise pg.GeometryError("gmsh produced no triangles.")
        tris = np.vstack(tri_list)
        keep = np.unique(tris)
        remap = np.full(len(tags), -1, dtype=np.int64)
        remap[keep] = np.arange(len(keep))
        nodes = coords[keep][:, :2]
        tris = remap[tris]
        p = nodes[tris]
        area2 = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
        flip = area2 < 0
        tris[flip] = tris[flip][:, [0, 2, 1]]

        def read_segs(curve_tags):
            segs = []
            for t in curve_tags:
                tys, _, nn = gmsh.model.mesh.getElements(1, t)
                for ty, arr in zip(tys, nn):
                    if ty != 1:
                        continue
                    a = remap[index[np.asarray(arr, dtype=np.int64)]].reshape(-1, 2)
                    segs += [(int(x), int(y)) for x, y in a if x >= 0 and y >= 0]
            return segs

        wall_segs = {edges[k]["src"]: read_segs(curve_tag[k]) for k in used}
        box_segs = {side: read_segs([box_curve[side]]) for side in SIDES}
        stats = pg.mesh_stats(nodes, tris)
        e1, e2, e3 = (np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1),
                      np.linalg.norm(p[:, 0] - p[:, 2], axis=1))
        alt = np.abs(area2) / np.maximum(np.maximum(e1, e2), e3)              # smallest height of each triangle
        stats.update({"h_body": h_body, "h_far": h_far, "transition": transition, "n_flipped": int(flip.sum()),
                      "algorithm": algorithm, "gmsh": getattr(gmsh, "__version__", "?"), "bl": dict(bl) if bl else None,
                      "corners": len(corner_list), "alt_min": float(alt.min()), "stretch_max": float((np.maximum(np.maximum(e1, e2), e3) / alt).max())})
        tick("Done", 1.0)
        return {"nodes": nodes, "tris": tris, "wall_segs": wall_segs, "box_segs": box_segs,
                "box": (bx0, by0, bx1, by1), "body_box": (xmin, ymin, xmax, ymax), "size": size, "stats": stats,
                "faces": [f["id"] for f in faces], "n_loops": len(loops)}
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


def mesh_fluid(m, geom, face_ids, margins, h_body, h_far, transition, progress=None, cancel=None, algorithm=6, bl=None,
               refine=None):
    """Same as mesh_fluid_once, but when gmsh cannot build the mesh (typically 'Edge not recovered': the boundary-layer stack is
    thicker than the room between walls, so layers from two walls run into each other) it is tried again with a thinner
    boundary layer, then without the corner fans.  What had to be relaxed is listed in stats["relaxed"]; if nothing works a
    plain explanation is raised instead of gmsh's own message."""
    t0 = bl["thickness"] if bl else None
    plans = []
    if bl:
        for corners in (True, False):
            for k in range(8):
                plans.append((dict(bl, thickness=t0 * 0.75 ** k), corners))
    else:
        plans = [(None, True), (None, False)]
    last = None
    for bl_i, corners in plans:
        if cancel and cancel():
            raise pg.Cancelled()
        try:
            mesh = mesh_fluid_once(m, geom, face_ids, margins, h_body, h_far, transition, progress, cancel, algorithm, bl_i, refine,
                                   use_corners=corners)
        except (pg.Cancelled, pg.GeometryError, ModelError):
            raise
        except Exception as ex:                                  # gmsh raises a bare Exception
            last = ex
            continue
        relaxed = []
        if bl_i and bl_i["thickness"] < t0 * 0.999:
            relaxed.append(f"boundary-layer thickness reduced from {t0:.4g} to {bl_i['thickness']:.4g} (sketch units): the full "
                           "thickness did not fit between the walls, so the layers cover only the inner part of the real boundary layer")
        if not corners:
            relaxed.append("no extra fans / refinement at sharp corners (the mesher could not build them)")
        mesh["stats"]["relaxed"] = relaxed
        return mesh
    raise pg.GeometryError(
        "The mesher could not build this mesh, even with a much thinner boundary layer. Usual causes: two walls that almost touch "
        "(a sliver or a gap narrower than the first layers), a very short edge next to large elements, or a self-touching outline. "
        "Try the gap report in the CFD diagnostics, weld touching points, or raise the element size at the body.  (gmsh said: "
        f"{last})")


# ----------------------------------------------------------------------------------------------
# boundary-layer sizing (wall-resolved turbulence)
# ----------------------------------------------------------------------------------------------
def bl_estimate(U, nu, L, yplus, ratio, first=None, thickness=None):
    """Flat-plate estimate of the first layer height and the boundary-layer thickness (metres).
    first / thickness override the estimates.  -> dict with y1, delta, layers, u_tau, Re, cf."""
    Re = max(U * L / nu, 1.0)
    cf = 0.026 * Re ** (-1.0 / 7.0)
    ut = U * math.sqrt(cf / 2.0)
    y1 = first if first else yplus * nu / ut
    delta = thickness if thickness else 0.37 * L * Re ** (-0.2)
    delta = max(delta, 5.0 * y1)
    n = int(math.ceil(math.log(1.0 + delta * (ratio - 1.0) / y1) / math.log(ratio)))
    return {"y1": y1, "delta": delta, "layers": n, "u_tau": ut, "Re": Re, "cf": cf}


# ----------------------------------------------------------------------------------------------
# edge geometry and position along an edge (used to hand pressures to the FEA tab)
# ----------------------------------------------------------------------------------------------
def edge_geometry(m, e):
    """Plain numbers describing a sketch edge, independent of any model."""
    if e["kind"] == "ln":
        a, b = m.pts[e["a"]], m.pts[e["b"]]
        return {"kind": "ln", "a": (float(a[0]), float(a[1])), "b": (float(b[0]), float(b[1]))}
    if e["kind"] == "ar":
        c = m.pts[e["c"]]
        a0, a1, r = pg.arc_angles(m, e)
        return {"kind": "ar", "c": (float(c[0]), float(c[1])), "r": float(r), "a0": a0, "a1": a1}
    c = m.pts[e["c"]]
    return {"kind": "ci", "c": (float(c[0]), float(c[1])), "r": float(e["r"])}


def edge_param(g, x, y):
    """Position of the point (x, y) along the edge, 0 at its start and 1 at its end (proportional to arc length).
    A circle starts at angle 0 and goes counter-clockwise."""
    if g["kind"] == "ln":
        ax, ay = g["a"]
        bx, by = g["b"]
        dx, dy = bx - ax, by - ay
        return ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
    cx, cy = g["c"]
    ang = math.atan2(y - cy, x - cx)
    if g["kind"] == "ci":
        return (ang % (2 * math.pi)) / (2 * math.pi)
    sweep = g["a1"] - g["a0"]
    rel = (ang - g["a0"]) % (2 * math.pi)
    if rel > sweep:
        rel = sweep if (rel - sweep) < (2 * math.pi - rel) else 0.0
    return rel / sweep


def edge_ends(g):
    if g["kind"] == "ln":
        return g["a"], g["b"]
    if g["kind"] == "ar":
        cx, cy = g["c"]
        r = g["r"]
        return ((cx + r * math.cos(g["a0"]), cy + r * math.sin(g["a0"])),
                (cx + r * math.cos(g["a1"]), cy + r * math.sin(g["a1"])))
    return None, None


def same_edge(g1, g2, tol):
    """True when two edge descriptions are the same piece of geometry (within tol)."""
    if g1["kind"] != g2["kind"]:
        return False
    if g1["kind"] == "ln":
        return all(abs(g1[k][i] - g2[k][i]) <= tol for k in ("a", "b") for i in (0, 1))
    ok = all(abs(g1["c"][i] - g2["c"][i]) <= tol for i in (0, 1)) and abs(g1["r"] - g2["r"]) <= tol
    if g1["kind"] == "ar":
        for q1, q2 in zip(edge_ends(g1), edge_ends(g2)):
            ok = ok and abs(q1[0] - q2[0]) <= tol and abs(q1[1] - q2[1]) <= tol
    return ok


def wall_segments_param(g, nodes, na, nb):
    """Edge positions (s_a, s_b) of mesh segments given by node arrays na, nb.  On a circle a segment that crosses the
    start gets an end above 1 so that each segment is one interval."""
    sa = np.array([edge_param(g, nodes[i][0], nodes[i][1]) for i in na])
    sb = np.array([edge_param(g, nodes[i][0], nodes[i][1]) for i in nb])
    if g["kind"] == "ci":
        wrap = np.abs(sb - sa) > 0.5
        up = wrap & (sa > sb)
        sb = np.where(up, sb + 1.0, sb)
        sa = np.where(wrap & ~up, sa + 1.0, sa)
    return sa, sb


# ----------------------------------------------------------------------------------------------
# quadrature and shape functions
# ----------------------------------------------------------------------------------------------
_S15 = math.sqrt(15.0)
_A1, _A2 = (6.0 - _S15) / 21.0, (6.0 + _S15) / 21.0
_B1, _B2 = 1.0 - 2.0 * _A1, 1.0 - 2.0 * _A2
QL = np.array([[1 / 3, 1 / 3, 1 / 3],
               [_A1, _A1, _B1], [_A1, _B1, _A1], [_B1, _A1, _A1],
               [_A2, _A2, _B2], [_A2, _B2, _A2], [_B2, _A2, _A2]])
QW = np.array([9.0 / 40.0] + [(155.0 - _S15) / 1200.0] * 3 + [(155.0 + _S15) / 1200.0] * 3)      # sums to 1; degree 5


def p2_shape(L):
    """6-node triangle shapes at barycentric points L (n,3): N (n,6) and dN/dlambda (n,6,3).
    Node order: 3 vertices, then the mid-edge nodes of edges (0,1), (1,2), (2,0)."""
    l1, l2, l3 = L[:, 0], L[:, 1], L[:, 2]
    N = np.stack([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1], axis=1)
    d = np.zeros((len(L), 6, 3))
    d[:, 0, 0] = 4 * l1 - 1
    d[:, 1, 1] = 4 * l2 - 1
    d[:, 2, 2] = 4 * l3 - 1
    d[:, 3, 0], d[:, 3, 1] = 4 * l2, 4 * l1
    d[:, 4, 1], d[:, 4, 2] = 4 * l3, 4 * l2
    d[:, 5, 2], d[:, 5, 0] = 4 * l1, 4 * l3
    return N, d


# ----------------------------------------------------------------------------------------------
# the discretisation
# ----------------------------------------------------------------------------------------------
class Disc:
    def __init__(self, nodes_sketch, tris, lscale):
        import scipy.sparse as sp
        self.sp = sp
        self.lscale = lscale
        Nv, M = len(nodes_sketch), len(tris)
        self.Nv, self.M = Nv, M
        self.tri = tris
        E = np.stack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=1)
        keys = np.minimum(E[..., 0], E[..., 1]).astype(np.int64) * Nv + np.maximum(E[..., 0], E[..., 1])
        ukeys, inv = np.unique(keys.ravel(), return_inverse=True)
        self.ukeys = ukeys
        inv = inv.reshape(M, 3)
        ne = len(ukeys)
        self.Nu = Nv + ne
        ea, eb = ukeys // Nv, ukeys % Nv
        self.xy_sketch = np.vstack([nodes_sketch, 0.5 * (nodes_sketch[ea] + nodes_sketch[eb])])
        self.xy = self.xy_sketch * lscale
        self.tri6 = np.concatenate([tris, Nv + inv], axis=1)
        self.edge_elem = np.zeros(ne, dtype=np.int64)
        self.edge_elem[inv.ravel()] = np.repeat(np.arange(M), 3)

        p = self.xy[tris]
        x, y = p[:, :, 0], p[:, :, 1]
        b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
        c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
        A = 0.5 * ((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
        if np.any(A <= 0):
            raise ModelError("The mesh has zero-area or inverted triangles.")
        self.A = A
        self.gx = b / (2 * A)[:, None]
        self.gy = c / (2 * A)[:, None]
        self.h = np.sqrt(2.0 * A)
        Lmax = np.maximum.reduce([np.hypot(x[:, 1] - x[:, 0], y[:, 1] - y[:, 0]), np.hypot(x[:, 2] - x[:, 1], y[:, 2] - y[:, 1]),
                                  np.hypot(x[:, 0] - x[:, 2], y[:, 0] - y[:, 2])])
        self.hd = 2.0 * A / Lmax                     # smallest height of the element
        self.Nq, self.dNdl = p2_shape(QL)
        self.dNdl_vertex = p2_shape(np.eye(3))[1]
        self.dNx = np.einsum("qmj,ej->eqm", self.dNdl, self.gx)
        self.dNy = np.einsum("qmj,ej->eqm", self.dNdl, self.gy)
        self.wA = QW[None, :] * A[:, None]

        t6 = self.tri6.astype(np.int32)
        self.rows66 = np.broadcast_to(t6[:, :, None], (M, 6, 6)).ravel()
        self.cols66 = np.broadcast_to(t6[:, None, :], (M, 6, 6)).ravel()
        Me = np.einsum("eq,qm,qn->emn", self.wA, self.Nq, self.Nq, optimize=True)
        Ke = (np.einsum("eq,eqm,eqn->emn", self.wA, self.dNx, self.dNx, optimize=True) +
              np.einsum("eq,eqm,eqn->emn", self.wA, self.dNy, self.dNy, optimize=True))
        self.Me, self.Ke = Me, Ke
        self.Mmat = self.scatter(Me)
        Bxe = np.einsum("eq,qi,eqm->eim", self.wA, QL, self.dNx, optimize=True)
        Bye = np.einsum("eq,qi,eqm->eim", self.wA, QL, self.dNy, optimize=True)
        rp = np.broadcast_to(tris.astype(np.int32)[:, :, None], (M, 3, 6)).ravel()
        cu = np.broadcast_to(t6[:, None, :], (M, 3, 6)).ravel()
        self.rows33 = np.broadcast_to(tris.astype(np.int32)[:, :, None], (M, 3, 3)).ravel()
        self.cols33 = np.broadcast_to(tris.astype(np.int32)[:, None, :], (M, 3, 3)).ravel()
        self.Mp1 = np.einsum("eq,qi,qj->eij", self.wA, QL, QL, optimize=True)
        self.dNdl_c = p2_shape(np.array([[1 / 3, 1 / 3, 1 / 3]]))[1][0]
        self.Bx = sp.coo_matrix((Bxe.ravel(), (rp, cu)), shape=(Nv, self.Nu)).tocsr()
        self.By = sp.coo_matrix((Bye.ravel(), (rp, cu)), shape=(Nv, self.Nu)).tocsr()

    def scatter(self, Ee):
        return self.sp.coo_matrix((Ee.ravel(), (self.rows66, self.cols66)), shape=(self.Nu, self.Nu)).tocsr()

    def scatter_p1(self, Ee):
        return self.sp.coo_matrix((Ee.ravel(), (self.rows33, self.cols33)), shape=(self.Nv, self.Nv)).tocsr()

    def strain2(self, u):
        """S^2 = 2 S_ij S_ij of the velocity at the centre of every element (exact for the quadratic velocity)."""
        u6 = u[self.tri6]
        dNx = np.einsum("mj,ej->em", self.dNdl_c, self.gx)
        dNy = np.einsum("mj,ej->em", self.dNdl_c, self.gy)
        gxx = (u6[:, :, 0] * dNx).sum(axis=1)
        gxy = (u6[:, :, 0] * dNy).sum(axis=1)
        gyx = (u6[:, :, 1] * dNx).sum(axis=1)
        gyy = (u6[:, :, 1] * dNy).sum(axis=1)
        sxy = 0.5 * (gxy + gyx)
        return 2.0 * (gxx ** 2 + gyy ** 2 + 2.0 * sxy ** 2)

    def mid_of(self, na, nb):
        na, nb = np.asarray(na, dtype=np.int64), np.asarray(nb, dtype=np.int64)
        key = np.minimum(na, nb) * self.Nv + np.maximum(na, nb)
        idx = np.searchsorted(self.ukeys, key)
        if np.any(idx >= len(self.ukeys)) or np.any(self.ukeys[np.minimum(idx, len(self.ukeys) - 1)] != key):
            raise ModelError("A boundary segment of the mesh is not an element edge (internal error).")
        return self.Nv + idx

    def segment_nodes(self, segs):
        if not segs:
            return np.zeros(0, dtype=np.int64)
        arr = np.asarray(segs, dtype=np.int64)
        return np.unique(np.concatenate([arr[:, 0], arr[:, 1], self.mid_of(arr[:, 0], arr[:, 1])]))

    def advance_matrix(self, a6, nu, dt):
        """Velocity block of the step matrix: M/dt + nu K + convection(a) + streamline diffusion(a)."""
        aq = np.einsum("qm,emc->eqc", self.Nq, a6)
        adv = aq[:, :, 0, None] * self.dNx + aq[:, :, 1, None] * self.dNy
        Ce = np.einsum("eq,qm,eqn->emn", self.wA, self.Nq, adv, optimize=True)
        speed = np.sqrt((aq ** 2).sum(axis=2))
        h = self.h[:, None]
        tau = 1.0 / np.sqrt((2.0 * speed / h) ** 2 + (4.0 * nu / h ** 2) ** 2)
        Se = np.einsum("eq,eqm,eqn->emn", self.wA * tau, adv, adv, optimize=True)
        return self.scatter(self.Me / dt + nu * self.Ke + Ce + Se)


def momentum_blocks_turb(disc, a6, nu_q, dt):
    """Velocity blocks for a variable viscosity nu_q (M, Q) in the full stress form (x and y velocities are coupled).
    -> Axx, Axy, Ayx, Ayy (sparse, Nu x Nu)"""
    aq = np.einsum("qm,emc->eqc", disc.Nq, a6)
    adv = aq[:, :, 0, None] * disc.dNx + aq[:, :, 1, None] * disc.dNy
    Ce = np.einsum("eq,qm,eqn->emn", disc.wA, disc.Nq, adv, optimize=True)
    adv1 = aq[:, :, 0, None] * disc.gx[:, None, :] + aq[:, :, 1, None] * disc.gy[:, None, :]
    s1 = np.abs(adv1).sum(axis=2)                              # = 2 |a| / (element length along the flow)
    tau = 1.0 / np.sqrt(s1 ** 2 + (4.0 * nu_q / disc.hd[:, None] ** 2) ** 2)
    Se = np.einsum("eq,eqm,eqn->emn", disc.wA * tau, adv, adv, optimize=True)
    T = disc.Me / dt + Ce + Se
    w = disc.wA * nu_q
    Kxx = np.einsum("eq,eqm,eqn->emn", w, disc.dNx, disc.dNx, optimize=True)
    Kyy = np.einsum("eq,eqm,eqn->emn", w, disc.dNy, disc.dNy, optimize=True)
    Kxy = np.einsum("eq,eqm,eqn->emn", w, disc.dNy, disc.dNx, optimize=True)      # d(w_x)/dy * d(u_y)/dx
    Kyx = np.einsum("eq,eqm,eqn->emn", w, disc.dNx, disc.dNy, optimize=True)      # d(w_y)/dx * d(u_x)/dy
    return (disc.scatter(T + 2.0 * Kxx + Kyy), disc.scatter(Kxy), disc.scatter(Kyx), disc.scatter(T + Kxx + 2.0 * Kyy))


BSTAR, A1 = 0.09, 0.31
SK1, SK2, SW1, SW2 = 0.85, 1.0, 0.5, 0.856
B1, B2, AL1, AL2 = 0.075, 0.0828, 5.0 / 9.0, 0.44


class Turbulence:
    """k-omega SST on the vertices of the mesh (linear elements, backward Euler, streamline diffusion)."""

    def __init__(self, disc, mesh, U, nu, intensity, ratio):
        from scipy.spatial import cKDTree
        self.disc, self.nu = disc, nu
        Nv = disc.Nv
        xy = disc.xy[:Nv]
        segs = np.asarray([sg for lst in mesh["wall_segs"].values() for sg in lst], dtype=np.int64)
        A, B = xy[segs[:, 0]], xy[segs[:, 1]]
        AB = B - A
        L2 = np.maximum((AB ** 2).sum(axis=1), 1e-300)
        tree = cKDTree(0.5 * (A + B))
        k = min(8, len(segs))
        _, cand = tree.query(xy, k=k)
        cand = cand.reshape(Nv, -1)
        dist = np.full(Nv, np.inf)
        for j in range(cand.shape[1]):
            c = cand[:, j]
            t = np.clip(((xy - A[c]) * AB[c]).sum(axis=1) / L2[c], 0.0, 1.0)
            q = A[c] + t[:, None] * AB[c]
            dist = np.minimum(dist, np.hypot(*(xy - q).T))
        self.dist = np.maximum(dist, 1e-12)
        self.dq = np.maximum(np.einsum("ei,qi->eq", self.dist[disc.tri], QL), 1e-12)
        wall_v = np.unique(segs)
        isw = np.zeros(Nv, dtype=bool)
        isw[wall_v] = True
        other = np.nonzero(~isw)[0]
        d1 = np.zeros(Nv)
        d1[wall_v] = np.maximum(cKDTree(xy[other]).query(xy[wall_v], k=1)[0], 1e-12)
        self.d1, self.wall_v = d1, wall_v
        self.k_in = 1.5 * (intensity * U) ** 2
        self.om_in = self.k_in / (nu * ratio)
        self.kmin = 1e-10 * U * U
        self.omin = max(1e-12, 1e-4 * self.om_in)
        self.fix_k = np.zeros(Nv, dtype=bool)
        self.fix_o = np.zeros(Nv, dtype=bool)
        self.val_k = np.zeros(Nv)
        self.val_o = np.zeros(Nv)
        self.set_wall_values()

    def set_inlet(self, inlet_vertices):
        self.fix_k[inlet_vertices] = True
        self.fix_o[inlet_vertices] = True
        self.val_k[inlet_vertices] = self.k_in
        self.val_o[inlet_vertices] = self.om_in
        self.set_wall_values()                                  # walls win at the corners

    def set_wall_values(self):
        w = self.wall_v
        self.fix_k[w] = True
        self.fix_o[w] = True
        self.val_k[w] = 0.0
        self.val_o[w] = 60.0 * self.nu / (B1 * self.d1[w] ** 2)

    def initial(self):
        Nv = self.disc.Nv
        kk = np.full(Nv, self.k_in)
        om = np.full(Nv, self.om_in)
        kk[self.fix_k] = self.val_k[self.fix_k]
        om[self.fix_o] = self.val_o[self.fix_o]
        return kk, om

    def at_qp(self, v):
        return np.einsum("ei,qi->eq", v[self.disc.tri], QL)

    def eddy(self, kk, om, S2e):
        """Eddy viscosity at the quadrature points, the blending functions and the cross-diffusion gradient product."""
        d = self.disc
        kq, oq = np.maximum(self.at_qp(kk), 0.0), np.maximum(self.at_qp(om), self.omin)
        gkx, gky = (kk[d.tri] * d.gx).sum(axis=1), (kk[d.tri] * d.gy).sum(axis=1)
        gox, goy = (om[d.tri] * d.gx).sum(axis=1), (om[d.tri] * d.gy).sum(axis=1)
        cross = (gkx * gox + gky * goy)[:, None]
        t1 = np.sqrt(kq) / (BSTAR * oq * self.dq)
        t2 = 500.0 * self.nu / (self.dq ** 2 * oq)
        CD = np.maximum(2.0 * SW2 * cross / oq, 1e-10)
        arg1 = np.minimum(np.maximum(t1, t2), 4.0 * SW2 * kq / (CD * self.dq ** 2))
        F1 = np.tanh(arg1 ** 4)
        F2 = np.tanh(np.maximum(2.0 * t1, t2) ** 2)
        nut = A1 * kq / np.maximum(A1 * oq, np.sqrt(S2e)[:, None] * F2)
        return nut, F1, kq, oq, cross

    def step(self, kk, om, u6, dt, S2e, nut, F1, kq, oq, cross):
        """One implicit step of the k and omega equations with the new velocity u6.  -> k, omega"""
        import scipy.sparse as sp
        import scipy.sparse.linalg as spla
        d, nu = self.disc, self.nu
        aq = np.einsum("qm,emc->eqc", d.Nq, u6)
        adv = aq[:, :, 0, None] * d.gx[:, None, :] + aq[:, :, 1, None] * d.gy[:, None, :]
        Ce = np.einsum("eq,qi,eqj->eij", d.wA, QL, adv, optimize=True)
        s1 = np.abs(adv).sum(axis=2)
        out = []
        for name, kk_old in (("k", kk), ("o", om)):
            if name == "k":
                sig = F1 * SK1 + (1 - F1) * SK2
                react = BSTAR * oq
                src = np.minimum(nut * S2e[:, None], 10.0 * BSTAR * kq * oq)
                fix, val = self.fix_k, self.val_k
            else:
                sig = F1 * SW1 + (1 - F1) * SW2
                beta = F1 * B1 + (1 - F1) * B2
                alpha = F1 * AL1 + (1 - F1) * AL2
                react = beta * oq
                src = alpha * S2e[:, None] + 2.0 * (1 - F1) * SW2 * cross / oq
                fix, val = self.fix_o, self.val_o
            G = nu + sig * nut
            tau = 1.0 / np.sqrt(s1 ** 2 + (4.0 * G / d.hd[:, None] ** 2) ** 2)
            De = (np.einsum("eq,ei,ej->eij", d.wA * G, d.gx, d.gx, optimize=True) +
                  np.einsum("eq,ei,ej->eij", d.wA * G, d.gy, d.gy, optimize=True))
            Se = np.einsum("eq,eqi,eqj->eij", d.wA * tau, adv, adv, optimize=True)
            Re = np.einsum("eq,qi,qj->eij", d.wA * react, QL, QL, optimize=True)
            Ae = d.Mp1 / dt + De + Ce + Se + Re
            Amat = d.scatter_p1(Ae)
            fe = np.einsum("eij,ej->ei", d.Mp1, kk_old[d.tri]) / dt + np.einsum("eq,qi,eq->ei", d.wA, QL, src)
            b = np.zeros(d.Nv)
            np.add.at(b, d.tri.ravel(), fe.ravel())
            free = (~fix).astype(float)
            g = np.where(fix, val, 0.0)
            Dm = sp.diags(free)
            Km = (Dm @ Amat @ Dm + sp.diags(1.0 - free)).tocsc()
            rhs = free * (b - Amat @ g) + g
            x = psolve.solve(Km, rhs)
            if not np.all(np.isfinite(x)):
                raise ModelError(f"The turbulence equation for {'k' if name == 'k' else 'omega'} diverged (NaN or infinity). "
                                 "Try a smaller time step (lower CFL) or a finer boundary-layer mesh.")
            out.append(np.maximum(x, self.kmin if name == "k" else self.omin))
        k_new, o_new = out
        k_new[self.fix_k] = self.val_k[self.fix_k]
        o_new[self.fix_o] = self.val_o[self.fix_o]
        return k_new, o_new


def classify_sides(angle_deg):
    d = (math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg)))
    out = {}
    for side, n in SIDE_NORMAL.items():
        nd = n[0] * d[0] + n[1] * d[1]
        out[side] = "inlet" if nd < -1e-9 else "outlet" if nd > 1e-9 else "slip"
    return out, d


def grad_at(disc, u, E, loc):
    """Velocity gradient G[i][j] = d u_i / d x_j at vertex `loc` (0..2) of elements E."""
    dN = disc.dNdl_vertex[loc]
    dNx = np.einsum("nmj,nj->nm", dN, disc.gx[E])
    dNy = np.einsum("nmj,nj->nm", dN, disc.gy[E])
    u6 = u[disc.tri6[E]]
    G = np.empty((len(E), 2, 2))
    G[:, :, 0] = np.einsum("nmi,nm->ni", u6, dNx)
    G[:, :, 1] = np.einsum("nmi,nm->ni", u6, dNy)
    return G


# ----------------------------------------------------------------------------------------------
# solve
# ----------------------------------------------------------------------------------------------
def suggested_dt(setup):
    return setup["cfl"] * setup["h_body"] * setup["lscale"] / setup["speed"]


def solve(mesh, setup, progress=None, frame=None, cancel=None):
    """Time-march to a steady state.
    setup: lscale, rho, mu, speed, angle, dt (or None = automatic), cfl, h_body, max_steps, tol, frame_every, edge_geoms.
    optional turbulence: turb (bool), intensity (fraction), visc_ratio.
    progress(step, max_steps, t, change_u, change_p, change_turbulence, seconds); frame(dict) every `frame_every` steps.
    until (bool): ignore max_steps and run until converged, until cancel(), or until on_stall(info) answers "stop".
    ramp_steps: the time step grows from 10 % to 100 % over this many steps (0 = off).
    on_stall(info) -> "continue" | "stop": asked when the change per step has stopped improving.
    -> result dict.  result["status"] is "converged", "max_steps", "stopped" (by the user) or "stalled"."""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    T0 = time.perf_counter()
    lscale, rho, mu, U = setup["lscale"], setup["rho"], setup["mu"], setup["speed"]
    if min(lscale, rho, mu, U) <= 0:
        raise ModelError("Speed, density, viscosity and the length unit must be positive.")
    until = bool(setup.get("until"))
    ramp = max(0, int(setup.get("ramp_steps", 0)))
    on_stall = setup.get("on_stall")
    if setup["tol"] <= 0 or setup["max_steps"] < 1:
        raise ModelError("The tolerance must be positive and the maximum number of steps at least 1.")
    nu = mu / rho
    dt = setup["dt"] if setup.get("dt") else suggested_dt(setup)
    if dt <= 0:
        raise ModelError("The time step must be positive.")

    disc = Disc(mesh["nodes"], mesh["tris"], lscale)
    Nu, Nv = disc.Nu, disc.Nv
    kinds, d = classify_sides(setup["angle"])
    if not any(v == "outlet" for v in kinds.values()) or not any(v == "inlet" for v in kinds.values()):
        raise ModelError("The wind direction gives no inlet or no outlet side.")

    fix = np.zeros((Nu, 2), dtype=bool)
    val = np.zeros((Nu, 2))
    for side in SIDES:                                       # priority: free-slip, then inlet, then walls
        if kinds[side] == "slip":
            ns = disc.segment_nodes(mesh["box_segs"][side])
            comp = 0 if side in ("left", "right") else 1
            fix[ns, comp] = True
            val[ns, comp] = 0.0
    for side in SIDES:
        if kinds[side] == "inlet":
            ns = disc.segment_nodes(mesh["box_segs"][side])
            fix[ns, :] = True
            val[ns, 0], val[ns, 1] = U * d[0], U * d[1]
    wall_nodes = disc.segment_nodes([s for segs in mesh["wall_segs"].values() for s in segs])
    fix[wall_nodes, :] = True
    val[wall_nodes, :] = 0.0

    fixed = np.concatenate([fix[:, 0], fix[:, 1], np.zeros(Nv, dtype=bool)])
    g = np.concatenate([np.where(fix[:, 0], val[:, 0], 0.0), np.where(fix[:, 1], val[:, 1], 0.0), np.zeros(Nv)])
    free = (~fixed).astype(float)
    Dm = sp.diags(free)
    Ifix = sp.diags(1.0 - free)
    BxT, ByT = disc.Bx.T.tocsr(), disc.By.T.tocsr()

    tb = None
    kk = om = None
    if setup.get("turb"):
        tb = Turbulence(disc, mesh, U, nu, setup["intensity"], setup["visc_ratio"])
        inl = [disc.segment_nodes(mesh["box_segs"][sd]) for sd in SIDES if kinds[sd] == "inlet"]
        iv = np.concatenate(inl) if inl else np.zeros(0, dtype=np.int64)
        tb.set_inlet(iv[iv < Nv])
        kk, om = tb.initial()
    nut_q = None
    u = np.zeros((Nu, 2))
    u[:, 0], u[:, 1] = U * d[0], U * d[1]
    u[fix[:, 0], 0] = val[fix[:, 0], 0]
    u[fix[:, 1], 1] = val[fix[:, 1], 1]
    pk = np.zeros(Nv)
    t = 0.0
    history = []
    status = "max_steps"
    quiet = 0
    t_assemble = t_solve = 0.0
    frame_every = max(1, int(setup.get("frame_every", 5)))
    step = 0
    max_steps = int(setup["max_steps"])
    stall_win = 200                                          # steps compared when looking for a stall
    next_check = stall_win * 2
    while True:
        step += 1
        if not until and step > max_steps:
            step -= 1
            break
        if cancel and cancel():
            status = "stopped"
            step -= 1
            break
        ts = time.perf_counter()
        dt_full = dt
        if ramp and step <= ramp:
            dt = dt_full * 0.1 ** (1.0 - (step - 1) / ramp)     # gentle start: 10 % of the time step, growing to 100 %
        if tb is not None:
            S2e = disc.strain2(u)
            nut_q, F1, kq, oq, cross = tb.eddy(kk, om, S2e)
            Axx, Axy, Ayx, Ayy = momentum_blocks_turb(disc, u[disc.tri6], nu + nut_q, dt)
            K = sp.bmat([[Axx, Axy, -BxT], [Ayx, Ayy, -ByT], [-disc.Bx, -disc.By, None]], format="csr")
        else:
            Auu = disc.advance_matrix(u[disc.tri6], nu, dt)
            K = sp.bmat([[Auu, None, -BxT], [None, Auu, -ByT], [-disc.Bx, -disc.By, None]], format="csr")
        b = np.concatenate([disc.Mmat @ u[:, 0] / dt, disc.Mmat @ u[:, 1] / dt, np.zeros(Nv)])
        rhs = free * (b - K @ g) + g
        Km = (Dm @ K @ Dm + Ifix).tocsc()
        t1 = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("error", category=spla.MatrixRankWarning)
            try:
                x = psolve.solve(Km, rhs)
            except spla.MatrixRankWarning:
                raise ModelError("The step matrix is singular (a part of the mesh may not be connected, or the boundary "
                                 "conditions do not fix the pressure).")
        t2 = time.perf_counter()
        t_assemble += t1 - ts
        t_solve += t2 - t1
        if not np.all(np.isfinite(x)):
            raise ModelError(f"The solution diverged at step {step} (NaN or infinity). Try a smaller time step (lower CFL), "
                             "a finer mesh, or a lower speed.")
        unew = np.stack([x[:Nu], x[Nu:2 * Nu]], axis=1)
        pnew = x[2 * Nu:]
        du = float(np.linalg.norm(unew - u) / max(np.linalg.norm(unew), 1e-300))
        dp = float(np.linalg.norm(pnew - pk) / (np.linalg.norm(pnew) + 1e-9 * 0.5 * U * U * math.sqrt(Nv)))
        u, pk = unew, pnew
        t += dt
        dturb = 0.0
        if tb is not None:
            S2n = disc.strain2(u)
            nut_q, F1, kq, oq, cross = tb.eddy(kk, om, S2n)
            k_new, o_new = tb.step(kk, om, u[disc.tri6], dt, S2n, nut_q, F1, kq, oq, cross)
            dturb = float(max(np.linalg.norm(k_new - kk) / max(np.linalg.norm(k_new), 1e-300),
                              np.linalg.norm(o_new - om) / max(np.linalg.norm(o_new), 1e-300)))
            kk, om = k_new, o_new
        history.append((step, t, du, dp, dturb))
        chg = max(du, dp, dturb)
        dt = dt_full
        if progress:
            progress(step, 0 if until else max_steps, t, du, dp, dturb, time.perf_counter() - ts)
        if frame and (step == 1 or step % frame_every == 0):
            frame(make_frame(disc, u, pk, rho, step, t, chg, tb, kk, om, nut_q, nu))
        quiet = quiet + 1 if (chg < setup["tol"] and step > ramp) else 0
        if quiet >= 3:
            status = "converged"
            break
        if until and on_stall is not None and step >= next_check:
            info = stall_info(history, stall_win, setup["tol"])
            if info is not None:
                if on_stall(info) == "stop":
                    status = "stalled"
                    break
                stall_win = min(stall_win * 2, 1600)         # asked once; ask again only after a longer stretch
            next_check = step + stall_win
    if frame and step >= 1 and (step % frame_every != 0 and step != 1):
        frame(make_frame(disc, u, pk, rho, step, t, max(history[-1][2:5]), tb, kk, om, nut_q, nu))

    res = {"status": status, "steps": step, "t": t, "dt": dt, "history": history, "until": until, "ramp_steps": ramp, "nu": nu, "rho": rho, "mu": mu,
           "speed": U, "angle": setup["angle"], "dir": d, "lscale": lscale, "sides": kinds, "tol": setup["tol"],
           "u": u, "p": rho * pk, "p_kin": pk, "n_u": Nu, "n_p": Nv, "tri6": disc.tri6, "xy_sketch": disc.xy_sketch,
           "gx": disc.gx, "gy": disc.gy, "q": 0.5 * rho * U * U,
           "re": rho * U * mesh["size"] * lscale / mu, "times": {"assemble": t_assemble, "solve": t_solve}}
    if tb is not None:
        res["turb"] = {"intensity": setup["intensity"], "visc_ratio": setup["visc_ratio"], "k_in": tb.k_in, "om_in": tb.om_in,
                       "k": kk, "omega": om, "d1": tb.d1,
                       "nut_ratio": (nut_q[:, 0] / nu) if nut_q is not None else np.zeros(disc.M)}
    res.update(postprocess(disc, mesh, res, setup["edge_geoms"]))
    res["times"]["total"] = time.perf_counter() - T0
    return res


def refine_indicator(mesh, res):
    """Error indicator per triangle for adaptive refinement: how much velocity and pressure change across the element
    (relative to the wind speed and the dynamic pressure), squared and weighted by the element area."""
    nodes, tris = mesh["nodes"], mesh["tris"]
    Nv = len(nodes)
    U = float(res["speed"])
    u, p = res["u"][:Nv], res["p_kin"][:Nv]
    q = 0.5 * U * U
    p3 = nodes[tris]
    area = 0.5 * np.abs((p3[:, 1, 0] - p3[:, 0, 0]) * (p3[:, 2, 1] - p3[:, 0, 1]) - (p3[:, 2, 0] - p3[:, 0, 0]) * (p3[:, 1, 1] - p3[:, 0, 1]))
    eta = np.zeros(len(tris))
    for a, b in ((0, 1), (1, 2), (2, 0)):
        du = np.linalg.norm(u[tris[:, a]] - u[tris[:, b]], axis=1) / U
        dp = np.abs(p[tris[:, a]] - p[tris[:, b]]) / q
        eta = np.maximum(eta, np.maximum(du, dp))
    return eta ** 2 * area


def stall_info(history, win, tol):
    """None while the change per step is still improving; otherwise a dict describing the stall.
    Compares the last `win` steps with the `win` before: the best change reached has to improve by at least 10 %."""
    if len(history) < 2 * win:
        return None
    ch = np.array([max(h[2:5]) for h in history])
    recent, before = ch[-win:], ch[-2 * win:-win]
    best_r, best_b = float(recent.min()), float(before.min())
    if best_r < tol * 10:
        return None                                          # close to the tolerance: let it finish
    last = float(np.mean(recent[-max(5, win // 20):]))
    first = float(np.mean(before[:max(5, win // 20)]))
    if best_r > 0.9 * best_b:
        kind = "diverging" if last > 3.0 * first else "stalled"
        return {"kind": kind, "step": len(history), "last": float(ch[-1]), "best_recent": best_r, "best_before": best_b,
                "win": win, "tol": tol, "spread": float(recent.max() / max(recent.min(), 1e-300))}
    return None


def make_frame(disc, u, pk, rho, step, t, change, tb=None, kk=None, om=None, nut_q=None, nu=None):
    Nv = disc.Nv
    fr = {"step": step, "t": t, "change": change, "ux": u[:Nv, 0].astype(np.float32),
          "uy": u[:Nv, 1].astype(np.float32), "p": (rho * pk).astype(np.float32)}
    if tb is not None:
        fr["k"] = kk.astype(np.float32)
        fr["omega"] = om.astype(np.float32)
        if nut_q is not None:
            fr["nut"] = (nut_q[:, 0] / nu).astype(np.float32)
    return fr


# ----------------------------------------------------------------------------------------------
# results on the walls, forces, mass balance
# ----------------------------------------------------------------------------------------------
def postprocess(disc, mesh, res, edge_geoms):
    u, pk, rho, mu, lscale = res["u"], res["p_kin"], res["rho"], res["mu"], res["lscale"]
    nodes = mesh["nodes"]
    walls = {}
    yplus = {}
    F_p = np.zeros(2)
    F_v = np.zeros(2)
    per_edge = {}
    for src, segs in mesh["wall_segs"].items():
        if not segs:
            continue
        arr = np.asarray(segs, dtype=np.int64)
        na, nb = arr[:, 0], arr[:, 1]
        key = np.minimum(na, nb) * disc.Nv + np.maximum(na, nb)
        E = disc.edge_elem[np.searchsorted(disc.ukeys, key)]
        T = disc.tri[E]
        la = np.argmax(T == na[:, None], axis=1)
        lb = np.argmax(T == nb[:, None], axis=1)
        pa, pb = nodes[na], nodes[nb]
        dd = pb - pa
        L = np.hypot(dd[:, 0], dd[:, 1])
        nf = np.stack([dd[:, 1], -dd[:, 0]], axis=1) / L[:, None]               # outward from the fluid, i.e. into the body
        cen = nodes[T].mean(axis=1)
        flip = (nf * (cen - 0.5 * (pa + pb))).sum(axis=1) > 0
        nf[flip] *= -1.0
        nbody = -nf                                                             # from the body into the fluid
        Ga, Gb = grad_at(disc, u, E, la), grad_at(disc, u, E, lb)
        tva = mu * np.einsum("nij,nj->ni", Ga + Ga.transpose(0, 2, 1), nbody)  # viscous traction on the body (Pa)
        tvb = mu * np.einsum("nij,nj->ni", Gb + Gb.transpose(0, 2, 1), nbody)
        p_a, p_b = rho * pk[na], rho * pk[nb]
        g = edge_geoms.get(src)
        if g is not None:
            s_a, s_b = wall_segments_param(g, nodes, na, nb)
        else:
            s_a = s_b = np.zeros(len(na))
        walls[src] = {"s_a": s_a, "s_b": s_b, "p_a": p_a, "p_b": p_b, "tv_a": tva, "tv_b": tvb, "L": L, "nf": nf}
        if res.get("turb") is not None:                                         # y+ of the first node off the wall
            d1 = res["turb"]["d1"]
            ya = d1[na] * np.sqrt(np.hypot(*tva.T) / rho) / res["nu"]
            yb = d1[nb] * np.sqrt(np.hypot(*tvb.T) / rho) / res["nu"]
            yp = np.concatenate([ya, yb])
            yplus[src] = (float(yp.min()), float(yp.mean()), float(yp.max()))
        Lm = L * lscale
        fp = (Lm * 0.5 * (p_a + p_b))[:, None] * nf
        fv = Lm[:, None] * 0.5 * (tva + tvb)
        F_p += fp.sum(axis=0)
        F_v += fv.sum(axis=0)
        per_edge[src] = (fp.sum(axis=0) + fv.sum(axis=0)).tolist()
    d = np.array(res["dir"])
    F = F_p + F_v
    forces = {"pressure": F_p.tolist(), "viscous": F_v.tolist(), "total": F.tolist(),
              "along": float(F @ d), "across": float(F @ np.array([-d[1], d[0]])), "per_edge": per_edge}

    flux = {}
    for side in SIDES:
        segs = mesh["box_segs"][side]
        if not segs:
            flux[side] = 0.0
            continue
        arr = np.asarray(segs, dtype=np.int64)
        na, nb = arr[:, 0], arr[:, 1]
        mid = disc.mid_of(na, nb)
        n = np.array(SIDE_NORMAL[side])
        un = lambda idx: u[idx] @ n
        L = np.hypot(*(nodes[nb] - nodes[na]).T) * lscale
        flux[side] = float(np.sum(L / 6.0 * (un(na) + 4.0 * un(mid) + un(nb))))
    inflow = -sum(v for s, v in flux.items() if res["sides"][s] == "inlet")
    net = sum(flux.values())
    mass = {"flux": flux, "inflow": inflow, "net": net, "relative": net / inflow if inflow > 0 else float("nan")}
    return {"walls": walls, "forces": forces, "mass": mass, "yplus": yplus}


# ----------------------------------------------------------------------------------------------
# sampling a result along a wall (for the FEA tab)
# ----------------------------------------------------------------------------------------------
def sample_wall(table, s, closed):
    """Pressure (Pa) and viscous traction (tx, ty in Pa) on the body at edge position s.
    The wall values are piecewise linear over the mesh segments; no averaging between segments."""
    lo = np.minimum(table["s_a"], table["s_b"])
    hi = np.maximum(table["s_a"], table["s_b"])
    cands = [s, s + 1.0] if closed else [s]
    best, dist_best = None, None
    for sv in cands:
        inside = np.nonzero((lo - 1e-12 <= sv) & (sv <= hi + 1e-12))[0]
        if len(inside):
            best, dist_best = (inside[0], sv), 0.0
            break
        dist = np.where(sv < lo, lo - sv, sv - hi)
        k = int(np.argmin(dist))
        if dist_best is None or dist[k] < dist_best:
            best, dist_best = (k, sv), float(dist[k])
    k, sv = best
    sa, sb = table["s_a"][k], table["s_b"][k]
    w = 0.0 if sb == sa else min(1.0, max(0.0, (sv - sa) / (sb - sa)))
    p = (1 - w) * table["p_a"][k] + w * table["p_b"][k]
    tv = (1 - w) * table["tv_a"][k] + w * table["tv_b"][k]
    return float(p), float(tv[0]), float(tv[1])


# ----------------------------------------------------------------------------------------------
# a velocity field that can be evaluated anywhere (tracer particles)
# ----------------------------------------------------------------------------------------------
class FlowField:
    def __init__(self, res):
        from scipy.spatial import cKDTree
        self.tri6 = res["tri6"]
        self.xy = res["xy_sketch"]
        self.u = res["u"]
        v = self.xy[self.tri6[:, :3]]
        self.v = v
        self.tree = cKDTree(v.mean(axis=1))

    def velocity(self, pts):
        """Velocity (m/s) at points (n,2) in sketch units -> (vel (n,2), inside (n,) bool)."""
        pts = np.asarray(pts, dtype=float)
        n = len(pts)
        k = min(12, len(self.v))
        _, cand = self.tree.query(pts, k=k)
        cand = cand.reshape(n, -1)
        elem = np.full(n, -1, dtype=np.int64)
        lam = np.zeros((n, 3))
        for j in range(cand.shape[1]):
            todo = np.nonzero(elem < 0)[0]
            if not len(todo):
                break
            e = cand[todo, j]
            x1, y1 = self.v[e, 0, 0], self.v[e, 0, 1]
            x2, y2 = self.v[e, 1, 0], self.v[e, 1, 1]
            x3, y3 = self.v[e, 2, 0], self.v[e, 2, 1]
            px, py = pts[todo, 0], pts[todo, 1]
            det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            l1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / det
            l2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / det
            l3 = 1.0 - l1 - l2
            ok = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            hit = todo[ok]
            elem[hit] = e[ok]
            lam[hit] = np.stack([l1[ok], l2[ok], l3[ok]], axis=1)
        inside = elem >= 0
        vel = np.zeros((n, 2))
        if np.any(inside):
            N, _ = p2_shape(lam[inside])
            u6 = self.u[self.tri6[elem[inside]]]
            vel[inside] = np.einsum("nm,nmc->nc", N, u6)
        return vel, inside
