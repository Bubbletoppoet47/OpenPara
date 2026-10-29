"""
Physics Calc - geometry side: closed regions found in a sketch, and the mesh made from them.

  analyze(model)          -> geom   edges, closed regions (faces), holes, nesting depth, problems found
  mesh_faces(...)         -> mesh   linear triangles from gmsh (needs the gmsh package)

Rules used to decide what is material:
  * Every closed loop of lines / arcs, and every circle, bounds a region.
  * Regions that share edges are meshed together (the mesh is conforming across the shared edge).
  * A loop that lies inside another loop is a hole in it (even-odd rule: inside a hole, material again).
  * Construction geometry is ignored.  Lines that are not part of a closed loop are ignored (and reported).
Each region can be switched on / off by the user before meshing.
"""
import math

import numpy as np


class Cancelled(Exception):
    pass


class GeometryError(Exception):
    pass


# ----------------------------------------------------------------------------------------------
# edges
# ----------------------------------------------------------------------------------------------
def build_edges(m):
    edges = []
    for lid, (a, b) in sorted(m.lns.items()):
        if ("ln", lid) in m.constr or a == b:
            continue
        edges.append({"src": ("ln", lid), "kind": "ln", "a": a, "b": b})
    for aid, ar in sorted(m.ars.items()):
        if ("ar", aid) in m.constr:
            continue
        edges.append({"src": ("ar", aid), "kind": "ar", "a": ar["s"], "b": ar["e"], "c": ar["c"]})
    for cid, c in sorted(m.cis.items()):
        if ("ci", cid) in m.constr or c["r"] <= 1e-12:
            continue
        edges.append({"src": ("ci", cid), "kind": "ci", "c": c["c"], "r": c["r"]})
    return edges


def arc_angles(m, e):
    c, s, t = m.pts[e["c"]], m.pts[e["a"]], m.pts[e["b"]]
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    a1 = math.atan2(t[1] - c[1], t[0] - c[0])
    while a1 <= a0:
        a1 += 2 * math.pi
    return a0, a1, math.hypot(s[0] - c[0], s[1] - c[1])


def edge_pts(m, e, n=180):
    """Points along an edge in its own direction a -> b (a circle: all the way round, first point not repeated)."""
    if e["kind"] == "ln":
        return [tuple(m.pts[e["a"]]), tuple(m.pts[e["b"]])]
    if e["kind"] == "ar":
        c = m.pts[e["c"]]
        a0, a1, r = arc_angles(m, e)
        k = max(8, int(math.ceil((a1 - a0) / (2 * math.pi) * n)))
        pts = [(c[0] + r * math.cos(a0 + (a1 - a0) * i / k), c[1] + r * math.sin(a0 + (a1 - a0) * i / k))
               for i in range(k + 1)]
        pts[0], pts[-1] = tuple(m.pts[e["a"]]), tuple(m.pts[e["b"]])
        return pts
    c = m.pts[e["c"]]
    return [(c[0] + e["r"] * math.cos(2 * math.pi * i / n), c[1] + e["r"] * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def seg_cross(p1, p2, p3, p4):
    """Proper crossing point of two segments, or None."""
    d1 = (p2[0] - p1[0], p2[1] - p1[1])
    d2 = (p4[0] - p3[0], p4[1] - p3[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-14:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / den
    u = ((p3[0] - p1[0]) * d1[1] - (p3[1] - p1[1]) * d1[0]) / den
    if 1e-9 < t < 1 - 1e-9 and 1e-9 < u < 1 - 1e-9:
        return (p1[0] + t * d1[0], p1[1] + t * d1[1])
    return None


def find_crossings(m, edges, polys):
    """Pairs of edges that cross each other away from a shared end point (they would make a bad mesh)."""
    out = []
    boxes = []
    for pts in polys:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            bi, bj = boxes[i], boxes[j]
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            pi, pj = polys[i], polys[j]
            if edges[i]["kind"] == "ci":
                pi = pi + [pi[0]]
            if edges[j]["kind"] == "ci":
                pj = pj + [pj[0]]
            hit = None
            for a in range(len(pi) - 1):
                for b in range(len(pj) - 1):
                    hit = seg_cross(pi[a], pi[a + 1], pj[b], pj[b + 1])
                    if hit:
                        break
                if hit:
                    break
            if hit:
                out.append((edges[i]["src"], edges[j]["src"], hit))
    return out


# ----------------------------------------------------------------------------------------------
# regions
# ----------------------------------------------------------------------------------------------
def find_gaps(m, edges, polys=None, rel=0.01):
    """Near misses: a free end of a line / arc (it belongs to only one edge) that lies within rel x (sketch size) of another
    free end or of another edge without being joined to it.  -> [{"kind", "a", "b", "dist", "at"}] nearest first.
    These are reported, never repaired."""
    names = {"ln": "Line", "ar": "Arc", "ci": "Circle"}
    open_edges = [k for k, e in enumerate(edges) if e["kind"] != "ci"]
    if not open_edges:
        return []
    if polys is None:
        polys = [edge_pts(m, e, 90) for e in edges]
    deg, owner = {}, {}
    for k in open_edges:
        for pid in (edges[k]["a"], edges[k]["b"]):
            deg[pid] = deg.get(pid, 0) + 1
            owner.setdefault(pid, k)
    xs = [p[0] for pts in polys for p in pts]
    ys = [p[1] for pts in polys for p in pts]
    near = rel * max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)
    ends = sorted(p for p, d in deg.items() if d == 1)

    def label(k):
        return f"{names[edges[k]['src'][0]]} {edges[k]['src'][1]}"
    gaps, in_gap = [], set()
    for i, p in enumerate(ends):
        for q in ends[i + 1:]:
            d = math.hypot(m.pts[p][0] - m.pts[q][0], m.pts[p][1] - m.pts[q][1])
            if d <= near and owner[p] != owner[q]:
                gaps.append({"kind": "end-end", "a": label(owner[p]), "b": label(owner[q]), "dist": d, "at": tuple(m.pts[p])})
                in_gap |= {p, q}
    for p in ends:
        if p in in_gap:
            continue
        px, py = m.pts[p]
        for k in open_edges:
            if k == owner[p] or p in (edges[k]["a"], edges[k]["b"]):
                continue
            pts = polys[k]
            best = min(_seg_dist(px, py, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            if best <= near:
                gaps.append({"kind": "end-edge", "a": label(owner[p]), "b": label(k), "dist": best, "at": (px, py)})
    gaps.sort(key=lambda g: g["dist"])
    return gaps


def _seg_dist(px, py, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / L2))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


def gap_text(g):
    if g["dist"] < 1e-12:
        return (f"the free end of {g['a']} sits exactly on {'the free end of ' if g['kind'] == 'end-end' else ''}{g['b']} near "
                f"({g['at'][0]:.4g}, {g['at'][1]:.4g}) but they are not joined (two separate points)")
    if g["kind"] == "end-end":
        return f"the free end of {g['a']} is {g['dist']:.3g} from the free end of {g['b']} near ({g['at'][0]:.4g}, {g['at'][1]:.4g})"
    return f"the free end of {g['a']} is {g['dist']:.3g} from {g['b']} near ({g['at'][0]:.4g}, {g['at'][1]:.4g})"


def gap_note(gaps, limit=2):
    if not gaps:
        return ""
    s = f" {len(gaps)} possible gap(s) in the sketch (ends that almost touch but are not joined): " + "; ".join(
        gap_text(g) for g in gaps[:limit]) + (" (and more - see the diagnostics)." if len(gaps) > limit else ".")
    return s


def analyze(m):
    """Find the closed regions of a sketch.  -> geom dict (see the keys at the end)."""
    edges = build_edges(m)
    polys = [edge_pts(m, e, 180) for e in edges]
    crossings = find_crossings(m, edges, polys)
    notes = []

    # drop lines / arcs that are not part of a closed loop (dangling ends)
    alive = [True] * len(edges)
    pruned = []
    while True:
        deg = {}
        for k, e in enumerate(edges):
            if alive[k] and e["kind"] != "ci":
                deg[e["a"]] = deg.get(e["a"], 0) + 1
                deg[e["b"]] = deg.get(e["b"], 0) + 1
        changed = False
        for k, e in enumerate(edges):
            if alive[k] and e["kind"] != "ci" and (deg[e["a"]] < 2 or deg[e["b"]] < 2):
                alive[k] = False
                pruned.append(e["src"])
                changed = True
        if not changed:
            break

    out = {}                                        # vertex -> outgoing half-edges (edge index, +1 / -1)
    for k, e in enumerate(edges):
        if not alive[k] or e["kind"] == "ci":
            continue
        for d, v in ((1, e["a"]), (-1, e["b"])):
            pts = polys[k] if d == 1 else polys[k][::-1]
            fine = edge_pts(m, e, 720)
            fine = fine if d == 1 else fine[::-1]
            dx, dy = fine[1][0] - fine[0][0], fine[1][1] - fine[0][1]
            out.setdefault(v, []).append((math.atan2(dy, dx), (k, d)))
    for v in out:
        out[v].sort(key=lambda t: t[0])
        out[v] = [h for _, h in out[v]]

    def he_pts(h):
        k, d = h
        pts = polys[k] if d == 1 else polys[k][::-1]
        return pts[:-1]

    def he_dest(h):
        k, d = h
        return edges[k]["b"] if d == 1 else edges[k]["a"]

    cycles = []
    seen = set()
    for v, lst in out.items():
        for h0 in lst:
            if h0 in seen:
                continue
            cyc, cur = [], h0
            while True:
                seen.add(cur)
                cyc.append(cur)
                w = he_dest(cur)
                twin = (cur[0], -cur[1])
                around = out[w]
                i = around.index(twin)
                cur = around[(i - 1) % len(around)]
                if cur == h0 or len(cyc) > 100000:
                    break
            cycles.append(cyc)

    # connected components of the line / arc graph
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for k, e in enumerate(edges):
        if alive[k] and e["kind"] != "ci":
            parent[find(e["a"])] = find(e["b"])
    comp_of_edge = {}
    comps = {}
    for k, e in enumerate(edges):
        if alive[k] and e["kind"] != "ci":
            c = find(e["a"])
            comp_of_edge[k] = c
            comps.setdefault(c, {"edges": [], "faces": [], "outer": None})["edges"].append(k)
    for cyc in cycles:
        poly = [p for h in cyc for p in he_pts(h)]
        area = poly_area(poly)
        comp = comps[comp_of_edge[cyc[0][0]]]
        item = {"cycle": cyc, "poly": poly, "area": area}
        if area > 1e-12:
            comp["faces"].append(item)
        else:
            comp["outer"] = item
    comp_list = list(comps.values())
    for k, e in enumerate(edges):                    # every circle is a component of its own
        if e["kind"] == "ci" and alive[k]:
            comp_list.append({"edges": [k],
                              "faces": [{"cycle": [(k, 1)], "poly": polys[k], "area": abs(poly_area(polys[k]))}],
                              "outer": {"cycle": [(k, -1)], "poly": polys[k][::-1], "area": -abs(poly_area(polys[k]))}})

    # nesting: which face (of another component) contains a component
    faces = []
    for ci, comp in enumerate(comp_list):
        for f in comp["faces"]:
            f["comp"] = ci
            f["id"] = len(faces)
            f["holes"] = []
            faces.append(f)
    depth = {}
    parent_face = {}
    for ci, comp in enumerate(comp_list):
        if comp["outer"] is None:
            continue
        probe = comp["outer"]["poly"][0]
        best = None
        for f in faces:
            if f["comp"] == ci:
                continue
            if point_in_poly(probe, f["poly"]) and (best is None or f["area"] < best["area"]):
                best = f
        parent_face[ci] = best
    for ci in range(len(comp_list)):
        d, cur, guard = 0, parent_face.get(ci), 0
        while cur is not None and guard < 1000:
            d += 1
            cur = parent_face.get(cur["comp"])
            guard += 1
        depth[ci] = d
    for ci, f in parent_face.items():
        if f is not None and comp_list[ci]["outer"] is not None:
            f["holes"].append(comp_list[ci]["outer"])
    for f in faces:
        f["depth"] = depth[f["comp"]]
        f["net_area"] = f["area"] + sum(h["area"] for h in f["holes"])          # hole areas are negative
        f["included"] = (f["depth"] % 2 == 0)
        xs = [p[0] for p in f["poly"]]
        ys = [p[1] for p in f["poly"]]
        f["centroid"] = (sum(xs) / len(xs), sum(ys) / len(ys))

    used = set()
    for f in faces:
        for h in f["cycle"]:
            used.add(h[0])
    for f in faces:
        for hole in f["holes"]:
            for h in hole["cycle"]:
                used.add(h[0])
    try:
        gaps = find_gaps(m, edges, polys)
    except Exception:
        gaps = []
    return {"edges": edges, "polys": polys, "faces": faces, "pruned": pruned, "crossings": crossings,
            "used_edges": used, "notes": notes, "n_components": len(comp_list), "gaps": gaps}


def face_geometry_ok(geom):
    if geom["crossings"]:
        txt = ", ".join(f"{a[0]}{a[1]} x {b[0]}{b[1]} near ({p[0]:.4g}, {p[1]:.4g})" for a, b, p in geom["crossings"][:6])
        raise GeometryError("Some edges cross each other without sharing a point, which cannot be meshed: " + txt +
                            ".  Split them at the crossing in the sketch (add a point there).")
    if not geom["faces"]:
        raise GeometryError("No closed loops found in the sketch (lines and arcs must form closed outlines).")


# ----------------------------------------------------------------------------------------------
# mesh (gmsh)
# ----------------------------------------------------------------------------------------------
def mesh_faces(m, geom, included, h, progress=None, cancel=None, algorithm=6, refine=None):
    """Linear triangles for the chosen faces.  h = target element size (sketch units).
    -> mesh dict: nodes (N,2), tris (M,3) counter-clockwise, tri_face (M,), curve_segs {(kind,id): [(na, nb)]},
       point_node {point id: node}, stats.
    refine = None, or {"nodes", "tris", "sizes"} (a previous mesh and the element size wanted at each of its nodes): the new mesh follows
    those sizes wherever they are smaller than h (adaptive refinement)."""
    import gmsh
    face_geometry_ok(geom)
    faces = [f for f in geom["faces"] if f["id"] in included]
    if not faces:
        raise GeometryError("No region is switched on.")
    if h <= 0:
        raise GeometryError("The element size must be positive.")

    def tick(txt, f):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(txt, f)

    edges, used = geom["edges"], set()
    for f in faces:
        for hh in f["cycle"]:
            used.add(hh[0])
        for hole in f["holes"]:
            for hh in hole["cycle"]:
                used.add(hh[0])

    try:
        gmsh.initialize(interruptible=False)
    except TypeError:
        gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("physics")
        tick("Building the geometry", 0.05)
        pt_tag = {}
        next_extra = [1000000]

        def gpoint(x, y, pid=None):
            if pid is not None:
                if pid not in pt_tag:
                    pt_tag[pid] = gmsh.model.geo.addPoint(x, y, 0.0, h, pid + 1)
                return pt_tag[pid]
            next_extra[0] += 1
            return gmsh.model.geo.addPoint(x, y, 0.0, h, next_extra[0])

        curve_tag = {}                                # edge index -> list of gmsh curve tags in the edge's own direction
        next_curve = [0]

        def gcurve(fn, *a):
            next_curve[0] += 1
            return fn(*a, next_curve[0])

        for k in sorted(used):
            e = edges[k]
            if e["kind"] == "ln":
                pa, pb = m.pts[e["a"]], m.pts[e["b"]]
                curve_tag[k] = [gcurve(gmsh.model.geo.addLine, gpoint(pa[0], pa[1], e["a"]), gpoint(pb[0], pb[1], e["b"]))]
            elif e["kind"] == "ar":
                c = m.pts[e["c"]]
                a0, a1, r = arc_angles(m, e)
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

        surf_of_face = {}
        for f in faces:
            loops = [gmsh.model.geo.addCurveLoop(loop_tags(f["cycle"]))]
            for hole in f["holes"]:
                loops.append(gmsh.model.geo.addCurveLoop(loop_tags(hole["cycle"])))
            surf_of_face[f["id"]] = gmsh.model.geo.addPlaneSurface(loops)
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.Algorithm", algorithm)
        gmsh.option.setNumber("Mesh.ElementOrder", 1)
        gmsh.option.setNumber("Mesh.RecombineAll", 0)
        if refine:
            background_from_sizes(gmsh, refine)
        tick("Meshing (gmsh)", 0.3)
        gmsh.model.mesh.generate(2)
        tick("Reading the mesh", 0.8)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        tags = np.asarray(tags, dtype=np.int64)
        coords = np.asarray(coords, dtype=float).reshape(-1, 3)
        index = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
        index[tags] = np.arange(len(tags))
        tri_list, tri_face = [], []
        for fid, stag in surf_of_face.items():
            types, _, enodes = gmsh.model.mesh.getElements(2, stag)
            for t, nodes in zip(types, enodes):
                if t != 2:
                    raise GeometryError("gmsh produced elements other than 3-node triangles.")
                arr = index[np.asarray(nodes, dtype=np.int64)].reshape(-1, 3)
                tri_list.append(arr)
                tri_face.append(np.full(len(arr), fid, dtype=np.int64))
        if not tri_list:
            raise GeometryError("gmsh produced no triangles.")
        tris = np.vstack(tri_list)
        tri_face = np.concatenate(tri_face)
        # keep only the nodes that belong to a triangle
        keep = np.unique(tris)
        remap = np.full(len(tags), -1, dtype=np.int64)
        remap[keep] = np.arange(len(keep))
        nodes = coords[keep][:, :2]
        tris = remap[tris]
        p = nodes[tris]
        area2 = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
        flip = area2 < 0
        tris[flip] = tris[flip][:, [0, 2, 1]]

        curve_segs, point_node = {}, {}
        for k in sorted(used):
            segs = []
            for t in curve_tag[k]:
                types, _, enodes = gmsh.model.mesh.getElements(1, t)
                for ty, nn in zip(types, enodes):
                    if ty != 1:
                        continue
                    a = remap[index[np.asarray(nn, dtype=np.int64)]].reshape(-1, 2)
                    segs += [(int(x), int(y)) for x, y in a if x >= 0 and y >= 0]
            curve_segs[edges[k]["src"]] = segs
        for pid, gt in pt_tag.items():
            nt, _, _ = gmsh.model.mesh.getNodes(0, gt, True, False)
            if len(nt):
                ni = remap[index[int(nt[0])]]
                if ni >= 0:
                    point_node[pid] = int(ni)
        stats = mesh_stats(nodes, tris)
        stats.update({"h": h, "n_flipped": int(flip.sum()), "algorithm": algorithm,
                      "gmsh": getattr(gmsh, "__version__", "?")})
        tick("Done", 1.0)
        return {"nodes": nodes, "tris": tris, "tri_face": tri_face, "curve_segs": curve_segs,
                "point_node": point_node, "stats": stats, "faces": [f["id"] for f in faces]}
    finally:
        try:
            gmsh.finalize()
        except Exception:
            pass


def mesh_stats(nodes, tris):
    p = nodes[tris]
    e = np.stack([np.linalg.norm(p[:, 1] - p[:, 0], axis=1), np.linalg.norm(p[:, 2] - p[:, 1], axis=1),
                  np.linalg.norm(p[:, 0] - p[:, 2], axis=1)], axis=1)
    area = 0.5 * ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    a, b, c = e[:, 0], e[:, 1], e[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.stack([np.arccos(np.clip((b**2 + c**2 - a**2) / (2 * b * c), -1, 1)),
                                   np.arccos(np.clip((a**2 + c**2 - b**2) / (2 * a * c), -1, 1)),
                                   np.arccos(np.clip((a**2 + b**2 - c**2) / (2 * a * b), -1, 1))], axis=1))
        s = e.sum(axis=1) / 2
        inr = np.where(s > 0, np.abs(area) / s, 0.0)
        aspect = e.max(axis=1) / (2 * np.sqrt(3) * np.where(inr > 0, inr, np.nan))
    return {"n_nodes": int(len(nodes)), "n_tris": int(len(tris)),
            "area_min": float(np.abs(area).min()), "area_mean": float(np.abs(area).mean()), "area_max": float(np.abs(area).max()),
            "edge_min": float(e.min()), "edge_max": float(e.max()),
            "angle_min": float(np.nanmin(ang)), "angle_max": float(np.nanmax(ang)),
            "aspect_max": float(np.nanmax(aspect)), "aspect_mean": float(np.nanmean(aspect)),
            "n_degenerate": int(np.sum(np.abs(area) < 1e-14 * max(1.0, float(np.abs(area).max()))))}


# ----------------------------------------------------------------------------------------------
# adaptive refinement (shared by the FEA and CFD tabs)
# ----------------------------------------------------------------------------------------------
MESH_TOL = 0.01          # the monitored values changed by less than this (relative) between two meshes = mesh converged


def node_sizes(nodes, tris):
    """Mean edge length of the triangles around each node."""
    p = nodes[tris]
    e = (np.linalg.norm(p[:, 1] - p[:, 0], axis=1) + np.linalg.norm(p[:, 2] - p[:, 1], axis=1) +
         np.linalg.norm(p[:, 0] - p[:, 2], axis=1)) / 3.0
    s, c = np.zeros(len(nodes)), np.zeros(len(nodes))
    for k in range(3):
        np.add.at(s, tris[:, k], e)
        np.add.at(c, tris[:, k], 1.0)
    return s / np.maximum(c, 1.0)


def mark_elements(eta2, theta=0.5):
    """Smallest set of elements that carries a fraction theta of the total squared error indicator (Doerfler marking)."""
    eta2 = np.asarray(eta2, dtype=float)
    mark = np.zeros(len(eta2), dtype=bool)
    if len(eta2) == 0 or not np.all(np.isfinite(eta2)):
        return mark
    order = np.argsort(eta2)[::-1]
    cum = np.cumsum(eta2[order])
    if cum[-1] <= 0:
        return mark
    n = int(np.searchsorted(cum, theta * cum[-1])) + 1
    mark[order[:n]] = True
    return mark


def refined_sizes(nodes, tris, marked, factor=0.5, grade=0.3, floor=0.0):
    """Element size wanted at every node of the current mesh: the current size, halved around the marked elements, never below
    `floor`, and graded so that it does not jump from one element to the next."""
    size = node_sizes(nodes, tris)
    new = size.copy()
    nm = np.unique(tris[marked].ravel()) if np.any(marked) else np.zeros(0, dtype=np.int64)
    new[nm] = size[nm] * factor
    new = np.maximum(new, floor)
    ed = np.vstack([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    ed = np.unique(np.sort(ed, axis=1), axis=0)
    d = np.linalg.norm(nodes[ed[:, 0]] - nodes[ed[:, 1]], axis=1)
    for _ in range(12):
        before = new.copy()
        np.minimum.at(new, ed[:, 0], new[ed[:, 1]] + grade * d)
        np.minimum.at(new, ed[:, 1], new[ed[:, 0]] + grade * d)
        if np.allclose(new, before, rtol=1e-6, atol=0.0):
            break
    return np.maximum(new, floor)


def background_from_sizes(gmsh, refine, others=()):
    """Makes the sizes of a previous mesh the gmsh background size field (the smaller of it and the fields in `others`)."""
    nodes, tris, sizes = np.asarray(refine["nodes"], float), np.asarray(refine["tris"]), np.asarray(refine["sizes"], float)
    p, v = nodes[tris], sizes[tris]
    data = np.concatenate([p[:, :, 0], p[:, :, 1], np.zeros((len(tris), 3)), v], axis=1)       # x1 x2 x3 y1 y2 y3 z1 z2 z3 v1 v2 v3
    vt = gmsh.view.add("size_background")
    gmsh.view.addListData(vt, "ST", len(tris), data.ravel().tolist())
    fld = gmsh.model.mesh.field
    fpv = fld.add("PostView")
    for opt, val in (("ViewTag", vt), ("ViewIndex", 0)):
        try:
            fld.setNumber(fpv, opt, val)
            break
        except Exception:
            continue
    top = fpv
    if others:
        top = fld.add("Min")
        fld.setNumbers(top, "FieldsList", [fpv] + list(others))
    fld.setAsBackgroundMesh(top)
    return top


def fea_indicator(nodes, tris, res):
    """Zienkiewicz-Zhu style error indicator per element: how far its (constant) stress is from the area-averaged stress at its
    nodes, times the element size.  Large where the stress changes quickly."""
    S = np.stack([res["sx"], res["sy"], res["txy"]], axis=1)
    A = np.abs(res["area"])
    num, den = np.zeros((len(nodes), 3)), np.zeros(len(nodes))
    for k in range(3):
        np.add.at(num, tris[:, k], S * A[:, None])
        np.add.at(den, tris[:, k], A)
    avg = num / np.maximum(den, 1e-300)[:, None]
    eta2 = np.zeros(len(tris))
    for k in range(3):
        d = S - avg[tris[:, k]]
        eta2 += d[:, 0] ** 2 + d[:, 1] ** 2 + 2.0 * d[:, 2] ** 2
    return eta2 * A
