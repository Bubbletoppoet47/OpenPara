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


def _edge_records(solid):
    """[{id, kind, length, mid, pts, sag}] of the edges of a solid: `pts` is the edge as a polyline (2 points for a line, 65 for a curve), in the order of
    solid.edges(); `sag` is how far the curve bulges away from the polyline at most (0 for a line)."""
    out = []
    for i, e in enumerate(solid.edges()):
        kind = str(e.geom_type).split(".")[-1].lower()
        try:
            ts = (0.0, 1.0) if kind == "line" else tuple(np.linspace(0.0, 1.0, 65))
            pts = [[p.X, p.Y, p.Z] for p in (e.position_at(t) for t in ts)]
            m = e.position_at(0.5)
            sag = 0.0
            if kind != "line":
                P = np.asarray(pts)
                tm = [(ts[k] + ts[k + 1]) / 2 for k in range(len(ts) - 1)]
                Q = np.array([[q.X, q.Y, q.Z] for q in (e.position_at(t) for t in tm)])
                sag = float(np.linalg.norm(Q - (P[:-1] + P[1:]) / 2, axis=1).max())
            out.append({"id": i, "kind": kind, "length": float(e.length), "mid": [m.X, m.Y, m.Z], "pts": pts, "sag": sag})
        except Exception:                                                      # noqa: BLE001 (an odd edge: it is just not offered)
            out.append({"id": i, "kind": kind, "length": 0.0, "mid": [0.0, 0.0, 0.0], "pts": [], "sag": 0.0})
    return out


def _analyze_solid(solid, full=True):
    """{faces, verts, step, diag, volume, bbox, tess} of one build123d Solid; full=False leaves out the tessellation and the STEP (not needed)."""
    import build123d as b
    if solid is None:
        raise GeomError("The part has no solid (it does not rebuild).")
    faces = []
    tess = []
    for i, f in enumerate(solid.faces()):
        c, n = f.center(b.CenterOf.MASS), f.normal_at()
        rec = {"id": i, "kind": str(f.geom_type).split(".")[-1].lower(), "center": [c.X, c.Y, c.Z], "normal": [n.X, n.Y, n.Z], "area": float(f.area)}
        if rec["kind"] == "cylinder":                                          # a round face (a hole, a boss): where its axis is and how wide: a bearing support needs it
            try:
                ax = f.axis_of_rotation
                rec["cyl"] = {"origin": [ax.position.X, ax.position.Y, ax.position.Z], "axis": [ax.direction.X, ax.direction.Y, ax.direction.Z],
                              "radius": float(f.radius)}
            except Exception:                                                  # noqa: BLE001 (an odd face: it is just not offered to a bearing)
                pass
        faces.append(rec)
    bb = solid.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    step = b""
    if full:
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
    return {"faces": faces, "verts": verts, "edges": _edge_records(solid), "step": step, "diag": diag, "volume": float(solid.volume), "tess": tess,
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]]}


def analyze(solid, splits=None):
    """{faces: [{id, kind, center, normal, area, parent, cell}], verts, step, diag, volume, bbox, tess, orig, split_of, notes} of a build123d Solid.

    splits = [{"face": face signature, "cols": n, "rows": m, "u": [x, y, z] or None, "col_sizes": [mm or None, ...], "row_sizes": [...]}]: each flat face
    is cut into n x m patches in the SOLID itself (see split_face), so the patches are real faces of the part and the mesh follows their edges.  A size
    that is None is "free": the free columns (rows) share what the fixed ones leave of the face, equally.  Every face then says which face of the UNSPLIT part it
    comes from ("parent", an id of g["orig"]) and, for a patch, its place in the grid ("cell" = (column, row), counted from 0).  Without splits
    g["orig"] is None (the part is its own original) and every face is its own parent.  g["notes"] lists splits that could not be applied."""
    splits = [s for s in (splits or []) if int(s.get("cols", 1)) * int(s.get("rows", 1)) > 1]
    if not splits:
        g = _analyze_solid(solid)
        for f in g["faces"]:
            f["parent"], f["cell"] = f["id"], None
        g.update({"orig": None, "split_of": {}, "notes": [], "solid": solid})
        return g
    g0 = _analyze_solid(solid, full=False)
    for f in g0["faces"]:
        f["parent"], f["cell"] = f["id"], None
    cur, records, split_of, notes = apply_splits(solid, g0, splits)
    g = _analyze_solid(cur)
    label_patches(g, g0, records, split_of)
    g.update({"orig": g0, "split_of": split_of, "notes": notes, "solid": cur})
    return g


def apply_splits(shape, g0, splits):
    """Cuts the faces of `shape` (a Solid, or a Compound of solids - an assembly) as the splits say; g0 = _analyze_solid of the unsplit shape with every
    face its own parent.  Returns (the new shape, records of the patches, {parent face id: split info}, notes)."""
    cur = shape
    records, split_of, notes = [], {}, []
    for sp in splits:
        pid = match_face(g0, sp["face"])
        if pid is None or pid in split_of:
            notes.append("A split face is not in the part any more; that split was left out." if pid is None else "A face was split twice; the first split is used.")
            continue
        f0 = g0["faces"][pid]
        if f0["kind"] != "plane":
            notes.append("Only flat faces can be split; a split of a curved face was left out.")
            continue
        face = _find_face(cur, f0["center"], f0["area"], g0["diag"])
        if face is None:
            notes.append("A split face could not be found in the part; that split was left out.")
            continue
        try:
            cur, u_used, patches, info = split_face(cur, face, int(sp["cols"]), int(sp["rows"]), sp.get("u"), sp.get("col_sizes"), sp.get("row_sizes"))
        except GeomError as ex:
            notes.append(str(ex))
            continue
        split_of[pid] = {"cols": int(sp["cols"]), "rows": int(sp["rows"]), "u": [float(x) for x in u_used], **info}
        for p in patches:
            records.append({"parent": pid, "cell": p["cell"], "center": p["center"], "area": p["area"]})
    return cur, records, split_of, notes


def label_patches(g, g0, records, split_of):
    """Gives every face of g (the analysis of the split shape) its parent in g0 and, for a patch, its cell."""
    tol = 1e-6 * max(g["diag"], 1.0)
    for f in g["faces"]:
        f["parent"], f["cell"] = None, None
        hit = next((r for r in records if _same(f, r["center"], r["area"], tol)), None)
        if hit is not None:
            f["parent"], f["cell"] = hit["parent"], tuple(hit["cell"])
            continue
        hit = next((o for o in g0["faces"] if o["id"] not in split_of and _same(f, o["center"], o["area"], tol)), None)
        f["parent"] = hit["id"] if hit is not None else None


def _same(f, center, area, tol):
    return (abs(f["area"] - area) <= 1e-6 * max(area, 1e-12) + 1e-12
            and float(np.linalg.norm(np.asarray(f["center"], float) - np.asarray(center, float))) <= tol)


def _find_face(solid, center, area, diag):
    tol = 1e-6 * max(diag, 1.0)
    import build123d as b
    for f in solid.faces():
        c = f.center(b.CenterOf.MASS)
        if _same({"center": [c.X, c.Y, c.Z], "area": float(f.area)}, center, area, tol):
            return f
    return None


WARN_PATCHES = 400                  # above this many patches the window asks first (a big grid is slow to cut and to mesh); there is no hard limit


def solve_sizes(total, n, fixed=None):
    """The n sizes (they add up to `total`) of the columns or rows of a grid: those given in `fixed` (a list of n numbers or None) stay, the free ones
    share what is left equally.  GeomError when the fixed ones leave nothing (or when none is free)."""
    fixed = list(fixed) if fixed else [None] * n
    if len(fixed) != n:
        raise GeomError("The sizes do not match the number of columns / rows.")
    free = [i for i, s in enumerate(fixed) if s is None]
    used = sum(float(s) for s in fixed if s is not None)
    if any(s is not None and float(s) <= 0 for s in fixed):
        raise GeomError("A size must be larger than zero.")
    if n == 1:
        return [float(total)]
    if not free:
        raise GeomError("At least one column (row) has to stay free, to take what the others leave.")
    left = float(total) - used
    if left <= 1e-9 * max(float(total), 1.0):
        raise GeomError(f"The fixed sizes add up to {used:.6g}, but the face is only {float(total):.6g} long: nothing is left for the free ones.")
    each = left / len(free)
    return [float(s) if s is not None else each for s in fixed]


def _vec(v):
    return np.array([v.X, v.Y, v.Z], float)


def _unit_sign(u):
    """A direction with its largest component positive (the same one after every rebuild)."""
    u = np.asarray(u, float)
    u = u / np.linalg.norm(u)
    return -u if u[int(np.argmax(np.abs(u)))] < 0 else u


def grid_frame(face, u_hint=None):
    """(origin, n, u, v, (umin, umax), (vmin, vmax)) of a flat face: columns run along u, rows along v = n x u.  u is the stored direction `u_hint`
    (projected into the plane) or, for a first split, the direction of the longer side of the face (the longest straight edge turned so that it is
    the long way of the face)."""
    n = _vec(face.normal_at())
    n /= np.linalg.norm(n)
    diag = float(np.linalg.norm([face.bounding_box().size.X, face.bounding_box().size.Y, face.bounding_box().size.Z]))
    V, _T = face.tessellate(max(diag * 1e-3, 1e-6), 0.2)
    P = np.array([[p.X, p.Y, p.Z] for p in V], float).reshape(-1, 3)
    if not len(P):
        raise GeomError("The face has no outline to split.")
    u = None
    if u_hint is not None:
        h = np.asarray(u_hint, float)
        h = h - np.dot(h, n) * n
        if np.linalg.norm(h) > 1e-6:
            u = h / np.linalg.norm(h)
    if u is None:
        best, bl = None, 0.0
        for e in face.edges():
            if str(e.geom_type).split(".")[-1].lower() != "line":
                continue
            d = _vec(e.end_point()) - _vec(e.start_point())
            if np.linalg.norm(d) > bl:
                best, bl = d, float(np.linalg.norm(d))
        if best is None:                                       # no straight edge (a disc): the long way of the outline
            C = np.cov((P - P.mean(axis=0)).T)
            w, vec = np.linalg.eigh(C)
            best = vec[:, int(np.argmax(w))]
            best = best - np.dot(best, n) * n
        u = _unit_sign(best - np.dot(best, n) * n)
        eu = np.ptp(P @ u)
        v0 = np.cross(n, u)
        if np.ptp(P @ v0) > eu * (1 + 1e-6):                   # the longest edge is the short side: columns run the other way
            u = _unit_sign(v0)
    v = np.cross(n, u)
    pu, pv = P @ u, P @ v
    return P.mean(axis=0), n, u, v, (float(pu.min()), float(pu.max())), (float(pv.min()), float(pv.max()))


def _at(point, axis, s):
    """A point of the plane {x : x . axis = s}, the one nearest to `point`."""
    return point + (s - float(np.dot(point, axis))) * axis


def _edges_of(shape):
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    out = []
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        out.append(TopoDS.Edge(ex.Current()))
        ex.Next()
    return out


def _section_edges(face, point, normal, R):
    """The edges where the plane through `point` with `normal` crosses the face (straight lines, cut to the face)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    pl = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*[float(x) for x in point]), gp_Dir(*[float(x) for x in normal])), -R, R, -R, R).Face()
    sec = BRepAlgoAPI_Section(face.wrapped, pl)
    sec.Build()
    return _edges_of(sec.Shape())


def _cut_face(solid, face, planes, R):
    """The solid with `face` cut along the given planes [(point, normal)]; (solid, number of lines added)."""
    import build123d as b
    from OCP.BRepFeat import BRepFeat_SplitShape
    from OCP.TopoDS import TopoDS
    sp = BRepFeat_SplitShape(solid.wrapped)
    n = 0
    for point, normal in planes:
        for e in _section_edges(face, point, normal, R):
            sp.Add(e, TopoDS.Face(face.wrapped))
            n += 1
    if n == 0:
        return solid, 0
    sp.Build()
    if not sp.IsDone():
        raise GeomError("The face could not be split here.")
    r = b.Shape.cast(sp.Shape())
    if not isinstance(solid, b.Solid):                                    # an assembly (a compound of solids) stays one
        if not isinstance(r, b.Compound):
            r = b.Compound([r])
        return r, n
    if not isinstance(r, b.Solid):
        sols = r.solids()
        if len(sols) != 1:
            raise GeomError("The face could not be split here.")
        r = sols[0]
    return r, n


def split_face(solid, face, cols, rows, u_hint=None, col_sizes=None, row_sizes=None):
    """Cuts a FLAT face of `solid` into cols x rows patches (columns along u, rows along v; the grid covers the face's bounding rectangle in that frame
    and is clipped to the face).  Equal ones, unless col_sizes / row_sizes fix some of them (see solve_sizes).  The cut goes into the solid, so the
    result has real faces.
    Returns (new solid, u used, [{"cell": (col, row), "center", "area"}], {"len_u", "len_v", "col_sizes", "row_sizes"}) - the sizes are the solved ones."""
    import build123d as b
    if cols < 1 or rows < 1 or cols * rows < 2:
        raise GeomError("Use at least 2 columns or rows (1 x 1 is no split).")
    if str(face.geom_type).split(".")[-1].lower() != "plane":
        raise GeomError("Only flat faces can be split.")
    o, n, u, v, (u0, u1), (v0, v1) = grid_frame(face, u_hint)
    bb = solid.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    R = 4.0 * diag + 1.0
    tol = 1e-6 * max(diag, 1.0)
    fc = face.center(b.CenterOf.MASS)
    area0 = float(face.area)
    plane_pt = _vec(fc)
    cs = solve_sizes(u1 - u0, cols, col_sizes)
    rs = solve_sizes(v1 - v0, rows, row_sizes)
    ue = u0 + np.concatenate([[0.0], np.cumsum(cs)])                    # the cut positions along u (cols + 1 values, the ends are the face's)
    ve = v0 + np.concatenate([[0.0], np.cumsum(rs)])
    ue[-1], ve[-1] = u1, v1
    col_planes = [(_at(plane_pt, u, float(x)), u) for x in ue[1:-1]]
    row_planes = [(_at(plane_pt, v, float(x)), v) for x in ve[1:-1]]
    cur = solid
    # the direction with fewer cuts goes first (one pass over the whole face); the second direction cuts every strip of it, one build each
    first, second = (col_planes, row_planes) if cols <= rows else (row_planes, col_planes)
    if first:
        cur, k = _cut_face(cur, face, first, R)
        if k == 0:
            raise GeomError("The cuts do not cross the face.")
    if second:
        subs = _patches_of(cur, solid, n, plane_pt, tol) if first else [face]
        keys = [(_vec(s.center(b.CenterOf.MASS)), float(s.area)) for s in subs]
        for c, a in keys:
            f = _find_face(cur, c, a, diag)
            if f is None:
                continue
            cur, _k = _cut_face(cur, f, second, R)
    patches = _patches_of(cur, solid, n, plane_pt, tol)
    if len(patches) < 2 or abs(sum(float(p.area) for p in patches) - area0) > 1e-6 * area0 or not cur.is_valid:
        raise GeomError("The face could not be split here.")
    out = []
    for p in patches:
        V, _T = p.tessellate(max(diag * 1e-3, 1e-6), 0.2)
        Pp = np.array([[q.X, q.Y, q.Z] for q in V], float).reshape(-1, 3)
        mu, mv = float((Pp @ u).min() + (Pp @ u).max()) / 2, float((Pp @ v).min() + (Pp @ v).max()) / 2
        i = int(min(max(np.searchsorted(ue, mu) - 1, 0), cols - 1))
        j = int(min(max(np.searchsorted(ve, mv) - 1, 0), rows - 1))
        c = p.center(b.CenterOf.MASS)
        out.append({"cell": (i, j), "center": [c.X, c.Y, c.Z], "area": float(p.area)})
    return cur, u, out, {"len_u": float(u1 - u0), "len_v": float(v1 - v0), "col_sizes": [float(x) for x in cs], "row_sizes": [float(x) for x in rs]}


def _patches_of(new, old_solid, n, plane_pt, tol):
    """The faces of `new` that are not in `old_solid`, lie in the plane through plane_pt and face the same way."""
    import build123d as b
    old = [{"center": [c.X, c.Y, c.Z], "area": float(f.area)} for f in old_solid.faces() for c in [f.center(b.CenterOf.MASS)]]
    out = []
    for f in new.faces():
        c = f.center(b.CenterOf.MASS)
        cc = np.array([c.X, c.Y, c.Z])
        if any(_same({"center": cc, "area": float(f.area)}, o["center"], o["area"], tol) for o in old):
            continue
        if abs(np.dot(_vec(f.normal_at()), n)) < 0.999 or abs(np.dot(cc - plane_pt, n)) > max(tol, 1e-6):
            continue
        out.append(f)
    return out


def grid_lines(g, fid, cols, rows, u_hint=None, col_sizes=None, row_sizes=None):
    """Segments [(p0, p1)] of the grid that split_face would cut into face `fid` of g (for the preview), or []."""
    solid = g.get("solid")
    if solid is None or cols < 1 or rows < 1:
        return []
    f0 = g["faces"][fid]
    if f0["kind"] != "plane":
        return []
    import build123d as b
    face = _find_face(solid, f0["center"], f0["area"], g["diag"])
    if face is None:
        return []
    o, n, u, v, (u0, u1), (v0, v1) = grid_frame(face, u_hint)
    plane_pt = _vec(face.center(b.CenterOf.MASS))
    R = 4.0 * g["diag"] + 1.0
    segs = []
    try:
        cs, rs = solve_sizes(u1 - u0, cols, col_sizes), solve_sizes(v1 - v0, rows, row_sizes)
    except GeomError:
        return []
    for axis, lo, sizes in ((u, u0, cs), (v, v0, rs)):
        for x in (lo + np.cumsum(sizes))[:-1]:
            for e in _section_edges(face, _at(plane_pt, axis, float(x)), axis, R):
                be = b.Edge(e)
                segs.append((_vec(be.start_point()), _vec(be.end_point())))
    return segs


def patch_outlines(g):
    """Segments [(p0, p1)] around every patch of a split face: the grid lines to draw in the view."""
    segs = []
    for f, (V, T) in zip(g["faces"], g["tess"]):
        if f.get("cell") is None or not len(T):
            continue
        cnt = {}
        for t in T:
            for a, c in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(a, c), max(a, c))
                cnt[k] = cnt.get(k, 0) + 1
        for (a, c), k in cnt.items():
            if k == 1:
                segs.append((V[a], V[c]))
    return segs


def _base_sig(f):
    s = {"type": "face", "kind": f["kind"], "center": list(f["center"]), "normal": list(f["normal"]), "area": f["area"]}
    if f.get("interface"):
        s["two_sided"] = True                  # a face between two bodies of an assembly: it has no outside, so its normal may come out either way round
    return s


def face_sig(g, fid):
    """The signature of a face to remember.  A whole face of the part is its signature in the UNSPLIT part (so it still means the whole face - all
    its patches - after the face is split); a patch is {the above for the patch + "parent": signature of the whole face, "cell": [col, row],
    "grid": [cols, rows]}."""
    f = g["faces"][fid]
    o = g.get("orig") or g
    p = f.get("parent", fid)
    if f.get("cell") is None:
        return _base_sig(o["faces"][p] if p is not None else f)
    s = _base_sig(f)
    sp = g["split_of"][p]
    s.update({"parent": _base_sig(o["faces"][p]), "cell": list(f["cell"]), "grid": [sp["cols"], sp["rows"]]})
    return s


def match_faces(g, sig):
    """The ids of the faces of `g` that a signature means (a whole face = all its patches), or None when it is gone."""
    o = g.get("orig") or g
    if "cell" in sig:
        pid = match_face(o, sig["parent"])
        sp = (g.get("split_of") or {}).get(pid)
        if pid is None or sp is None or [sp["cols"], sp["rows"]] != list(sig["grid"]):
            return None
        ids = [f["id"] for f in g["faces"] if f.get("parent") == pid and f.get("cell") == tuple(sig["cell"])]
        return ids or None
    pid = match_face(o, sig)
    if pid is None:
        return None
    ids = [f["id"] for f in g["faces"] if f.get("parent", f["id"]) == pid]
    return ids or None


def vert_sig(g, vid):
    return {"type": "vertex", "point": list(g["verts"][vid])}


def edge_sig(g, eid):
    """The signature of an edge to remember: its kind, where its middle is, how long it is and where it ends."""
    e = g["edges"][eid]
    pts = e["pts"]
    return {"type": "edge", "kind": e["kind"], "mid": list(e["mid"]), "length": e["length"], "ends": [list(pts[0]), list(pts[-1])] if pts else []}


def match_edge(g, sig, tol=0.6):
    """The id of the edge of `g` that the signature means, or None: the same kind of curve, the nearest middle, a similar length."""
    best, bd = None, None
    d0 = max(g["diag"], 1e-12)
    for e in g.get("edges") or []:
        if e["kind"] != sig["kind"] or not e["pts"]:
            continue
        dist = float(np.linalg.norm(np.asarray(e["mid"]) - sig["mid"])) / d0
        dist += 0.1 * abs(e["length"] - sig["length"]) / max(sig["length"], 1e-12) * (1 if dist > 0.02 else 0.2)
        if bd is None or dist < bd:
            best, bd = e["id"], dist
    return best if bd is not None and bd <= tol else None


def edge_chain(g, eid, nodes, n_corner, order=2):
    """The mesh nodes along edge `eid` of the geometry `g`.  `nodes` = every node of the mesh, the first `n_corner` of them are the corners of the elements, the rest (a
    quadratic mesh) the middles of the element edges.  -> {"nodes": node ids along the edge (corners and middles, in order), "w": the share of a load along the edge that
    each carries (sums to 1), "cover": the part of the edge's length the chain spans (0..1), "closed", "ok": every piece between neighbouring nodes is an element edge,
    "n": how many pieces}.  "nodes" is empty when the mesh has no node along the edge: it does not follow it (nothing is approximated)."""
    e = g["edges"][eid]
    return poly_chain(e["pts"], nodes, n_corner, g["diag"], e.get("sag", 0.0), order)


def poly_chain(pts, nodes, n_corner, diag, sag=0.0, order=2):
    """edge_chain for an edge given as a polyline.  A corner node of the mesh is on the edge when it lies on the edge's curve (within the sag of the polyline and a hair); the
    middle node of an element edge between two neighbours on the edge is found as their midpoint (a quadratic mesh has straight element edges)."""
    out = {"nodes": np.zeros(0, int), "w": np.zeros(0), "cover": 0.0, "closed": False, "ok": False, "n": 0}
    pts = np.asarray(pts, float)
    if len(pts) < 2:
        return out
    N = np.asarray(nodes, float)
    n_corner = int(n_corner)
    tol = 2e-5 * max(diag, 1e-12) + 1.2 * float(sag)
    lo, hi = pts.min(axis=0) - tol, pts.max(axis=0) + tol
    cand = np.where(np.all((N[:n_corner] >= lo) & (N[:n_corner] <= hi), axis=1))[0]
    if len(cand) < 2:
        return out
    a, b = pts[:-1], pts[1:]
    ab = b - a
    seg = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-24)
    X = N[cand]
    t = np.clip(np.einsum("nsj,sj->ns", X[:, None, :] - a[None], ab) / seg[None], 0.0, 1.0)
    d = np.linalg.norm(a[None] + ab[None] * t[:, :, None] - X[:, None, :], axis=2)
    k = d.argmin(axis=1)
    rows = np.arange(len(cand))
    keep = d[rows, k] <= tol
    if keep.sum() < 2:
        return out
    seglen = np.sqrt(seg)
    start = np.concatenate([[0.0], np.cumsum(seglen)])[:-1]
    total = float(seglen.sum())
    s_arc = start[k[keep]] + t[rows[keep], k[keep]] * seglen[k[keep]]
    idx = cand[keep]
    closed = bool(np.linalg.norm(pts[0] - pts[-1]) <= 1e-9 * max(diag, 1.0))
    if closed:
        s_arc = np.where(s_arc >= total - 1e-9 * max(total, 1.0), 0.0, s_arc)             # the seam node is the start
    order_ = np.argsort(s_arc)
    idx, s_arc = idx[order_], s_arc[order_]
    cover = 1.0 if closed else float((s_arc[-1] - s_arc[0]) / total if total > 0 else 0.0)
    pairs = list(zip(idx[:-1], idx[1:])) + ([(idx[-1], idx[0])] if closed and len(idx) > 2 else [])
    ok = True
    if order == 2:
        mid_idx = np.arange(n_corner, len(N))
        MN = N[mid_idx] if len(mid_idx) else np.zeros((0, 3))
    acc = {}
    for p, q_ in pairs:
        L = float(np.linalg.norm(N[p] - N[q_]))
        if order == 2:
            m = None
            if len(MN):
                dd = np.linalg.norm(MN - (N[p] + N[q_]) / 2, axis=1)
                j = int(dd.argmin())
                if dd[j] <= 1e-6 * max(diag, 1.0):
                    m = int(mid_idx[j])
            if m is None:
                ok = False
                continue
            for node, w in ((p, L / 6), (m, 4 * L / 6), (q_, L / 6)):
                acc[node] = acc.get(node, 0.0) + w
        else:
            for node, w in ((p, L / 2), (q_, L / 2)):
                acc[node] = acc.get(node, 0.0) + w
    if not acc:
        return out
    ids = sorted(acc, key=lambda nd: (np.dot(N[nd] - N[idx[0]], N[idx[-1]] - N[idx[0]]), nd)) if not closed else sorted(acc)
    tot = sum(acc.values())
    out.update({"nodes": np.array(ids, int), "w": np.array([acc[nd] / tot for nd in ids]), "cover": cover, "closed": closed, "ok": ok, "n": len(pairs)})
    return out


def match_face(g, sig, tol=0.6):
    """The id of the face of `g` that the signature means, or None.  Same kind of surface and a similar normal; the nearest centre wins."""
    best, bd = None, None
    d0 = max(g["diag"], 1e-12)
    n0 = np.asarray(sig["normal"], float)
    for f in g["faces"]:
        if f["kind"] != sig["kind"]:
            continue
        dn = float(np.dot(n0, f["normal"]))
        if (abs(dn) if sig.get("two_sided") else dn) < 0.7 and sig["kind"] == "plane":
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


def display_mesh(g, hidden=()):
    """One triangle mesh of all faces for the 3D view: (points, triangles, face id per triangle).  hidden = bodies of an assembly that are not drawn: their
    outer faces go, and a face between a hidden body and a shown one is drawn (it is then the surface of the shown one, and can be picked)."""
    P, T, F = [], [], []
    off = 0
    hidden = set(hidden or ())
    for i, (v, t) in enumerate(g["tess"]):
        f = g["faces"][i]
        if not len(t):
            continue
        if f.get("interface"):                                         # a face between two bodies of an assembly is inside: drawn only when a body is hidden
            bs = f.get("bodies") or []
            if not (hidden and any(b in hidden for b in bs) and any(b not in hidden for b in bs)):
                continue
        elif hidden and f.get("body") in hidden:
            continue
        P.append(v)
        T.append(t + off)
        F.append(np.full(len(t), i))
        off += len(v)
    if not P:
        return np.zeros((0, 3)), np.zeros((0, 3), int), np.zeros(0, int)
    return np.vstack(P), np.vstack(T), np.concatenate(F)
