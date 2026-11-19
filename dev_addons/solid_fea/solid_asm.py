"""
solid_asm.py - an ASSEMBLY as one bonded geometry for the 3D FEA add-on.  No window in it.

The bodies of the assembly (each part, placed where its mates put it) are put through one "general fuse" with a distance: faces that lie within that
distance of each other, face to face, become ONE shared face, so the mesh has the same nodes on both sides - the bodies are fully bonded there (no
slip, no gap, no separation).  Every body keeps its own volume (its own material); the shared faces are the "interfaces".

  analyze_assembly(bodies, tol)   ->  a geometry dict like solid_geom.analyze's (faces, verts, step, tess, bbox, ...) plus
      "bodies":  [{"name", "material" (E, nu, rho, sy, su, name - solver units), "volume", "faces": [face ids on the outside of the body]}]
      "solids":  [{"body", "center", "volume"}]       the pieces the fuse made (a body overlapped by another is cut into pieces); the mesher matches them
      "bonds":   [{"a", "b", "area", "faces": [face ids]}]      bodies that share faces, with the area bonded
      "groups":  [[body, ...], ...]                    sets of bodies that hold together (several groups = parts that touch nothing of the others)
      "floating": [body, ...]                          bodies in a group that is not the biggest one
      "hints":   [text, ...]                            "X is 0.4 mm from Y: raise the bond distance to bond them"
      "overlaps": [{"a", "b", "volume"}]                bodies that share volume (the overlap belongs to the first one)
      "notes":   [text, ...]
    and every face carries "body" (the body it belongs to), "interface" (True: it lies inside, between two pieces) and "bodies" (the bodies on its sides).

Units are mm.
"""
import numpy as np

import solid_geom as sg


class AsmError(Exception):
    pass


def auto_tol(diag):
    """The bond distance when none is given: about a ten-thousandth of the size of the assembly (and not below a thousandth of a mm)."""
    return max(1e-4 * float(diag), 1e-3)


def body_material(m):
    """A part's material (the assembly file's: density, E_MPa, nu, Sy_MPa, Su_MPa) as the solver's material dict."""
    m = m or {}
    return {"E": float(m.get("E_MPa") or 200000.0), "nu": float(m.get("nu") or 0.3), "rho": float(m.get("density") or 7850.0),
            "sy": float(m.get("Sy_MPa") or 0.0), "su": float(m.get("Su_MPa") or 0.0), "name": m.get("name") or ""}


def bodies_of_source(src):
    """[(name, placed solid, material dict)] of an assembly source (sim_source.AsmSource); names are made unique."""
    import asm_sub
    out, seen = [], {}
    for n, s, m in asm_sub.bodies_of(src, src.asm):
        k = seen.get(n, 0) + 1
        seen[n] = k
        out.append((n if k == 1 else f"{n} ({k})", s, m))
    if not out:
        raise AsmError("The assembly has no visible part with a solid.")
    return out


def _fuse(solids, tol):
    """The general fuse of the solids with the distance `tol`: (compound of the pieces, [[piece index, ...] per solid])."""
    from build123d import Compound, Shape
    from OCP.BOPAlgo import BOPAlgo_Builder
    if len(solids) == 1:                                                    # nothing to join
        res = Compound(list(solids))
        return res, res.solids(), [[0]]
    b = BOPAlgo_Builder()
    for s in solids:
        b.AddArgument(s.wrapped)
    b.SetFuzzyValue(float(tol))
    b.SetRunParallel(False)
    b.Perform()
    if b.HasErrors():
        raise AsmError("The bodies of the assembly could not be joined (the geometry is too damaged for the boolean operation). "
                       "Try a smaller or a larger bond distance.")
    res = Compound(b.Shape())
    pieces = res.solids()
    imgs = b.Images()
    owners = []
    for s in solids:
        mine = [k for k, p in enumerate(pieces) if p.wrapped.IsSame(s.wrapped)]           # a body the fuse left alone is a piece itself
        try:
            for x in imgs.Find(s.wrapped):                                                  # else the pieces it was cut into
                for q in Shape.cast(x).solids():
                    mine += [k for k, p in enumerate(pieces) if p.wrapped.IsSame(q.wrapped) and k not in mine]
        except Exception:
            pass
        owners.append(mine)
    _by_position(solids, pieces, owners)
    return res, pieces, owners


def _inside_point(piece):
    """A point inside a piece: its centre of mass if that lies in it, else a point just inside one of its faces (None if none is found)."""
    import build123d as b
    c = piece.center(b.CenterOf.MASS)
    if piece.is_inside(c):
        return c
    for f in piece.faces()[:12]:
        p, n = f.center(b.CenterOf.MASS), f.normal_at()
        for d in (1e-2, 1e-3, 1e-1):
            q = p - n * (d * max(piece.bounding_box().diagonal, 1e-9) * 0.1)
            if piece.is_inside(q):
                return q
    return None


def _by_position(solids, pieces, owners):
    """Pieces that no body claimed through the history of the fuse belong to the bodies that contain a point inside them."""
    claimed = {k for o in owners for k in o}
    for k, p in enumerate(pieces):
        if k in claimed:
            continue
        pt = _inside_point(p)
        if pt is None:
            continue
        for i, s in enumerate(solids):
            try:
                if s.is_inside(pt):
                    owners[i].append(k)
            except Exception:
                pass


def _face_pieces(res, pieces):
    """[set of piece indices that a face of the compound belongs to] in the order of res.faces()."""
    table = {}
    for k, p in enumerate(pieces):
        for f in p.faces():
            table.setdefault(hash(f.wrapped), []).append((k, f))
    out = []
    for f in res.faces():
        out.append({k for k, g in table.get(hash(f.wrapped), ()) if g.wrapped.IsSame(f.wrapped)})
    return out


def _groups(n, pairs):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in pairs:
        parent[find(a)] = find(b)
    d = {}
    for i in range(n):
        d.setdefault(find(i), []).append(i)
    return sorted(d.values(), key=lambda g: g[0])


def _mark_faces(g, res, pieces, piece_body):
    """Every face of g (the analysis of the compound `res`): the bodies on its sides ("bodies"), the first of them ("body"), and "interface" (it lies
    between two pieces, so inside the assembly)."""
    fp = _face_pieces(res, pieces)
    for f, ps in zip(g["faces"], fp):
        bs_ = sorted({piece_body[k] for k in ps})
        f["interface"] = len(ps) >= 2
        f["bodies"] = bs_
        f["body"] = bs_[0] if bs_ else 0


def _carry_owners(old_pieces, old_body, new_pieces, scale):
    """{new piece index: body}: a split changes the faces of a piece, not its shape, so every new piece is the old one with the same centre and volume."""
    import build123d as b123
    def centre(p):
        c = p.center(b123.CenterOf.MASS)
        return np.array([c.X, c.Y, c.Z])
    old = [(centre(p), float(p.volume), old_body[k]) for k, p in enumerate(old_pieces)]
    out = {}
    for k, p in enumerate(new_pieces):
        c = centre(p)
        v = float(p.volume)
        best = min(old, key=lambda o: float(np.linalg.norm(c - o[0])) / scale + abs(v - o[1]) / max(o[1], 1e-12))
        out[k] = best[2]
    return out


def analyze_assembly(bodies, tol=0.0, splits=None):
    """See the top of the file.  bodies = [(name, solid, material dict as in the part file)], tol = bond distance in mm (0 = automatic),
    splits = the face splits of the setup (see solid_geom.analyze); they cut the faces of the FUSED assembly, so a face between two bodies can be split
    too (the patches are then shared by both bodies)."""
    import build123d as b123
    solids = [s for _n, s, _m in bodies]
    n = len(solids)
    if n == 0:
        raise AsmError("The assembly has no parts.")
    bb = [s.bounding_box() for s in solids]
    lo = np.min([[b.min.X, b.min.Y, b.min.Z] for b in bb], axis=0)
    hi = np.max([[b.max.X, b.max.Y, b.max.Z] for b in bb], axis=0)
    diag = float(np.linalg.norm(hi - lo))
    tol_used = float(tol) if tol and float(tol) > 0 else auto_tol(diag)
    res, pieces, owners = _fuse(solids, tol_used)
    if not pieces:
        raise AsmError("The assembly has no solid after the bodies were joined.")
    notes = []
    lost = [bodies[i][0] for i in range(n) if not owners[i]]
    if lost:
        notes.append("Not found in the joined geometry (left out): " + ", ".join(lost) + ".")
    piece_body = {}
    overlaps = {}
    for i in range(n):
        for k in owners[i]:
            if k not in piece_body:
                piece_body[k] = i
            else:
                key = (piece_body[k], i)
                overlaps[key] = overlaps.get(key, 0.0) + float(pieces[k].volume)
    stray = [k for k in range(len(pieces)) if k not in piece_body]
    for k in stray:
        piece_body[k] = 0
    splits = [x for x in (splits or []) if int(x.get("cols", 1)) * int(x.get("rows", 1)) > 1]
    g0 = None
    split_of = {}
    if splits:
        g0 = sg._analyze_solid(res, full=False)
        for f in g0["faces"]:
            f["parent"], f["cell"] = f["id"], None
        _mark_faces(g0, res, pieces, piece_body)
        cur, records, split_of, snotes = sg.apply_splits(res, g0, splits)
        notes += snotes
        new_pieces = cur.solids()
        piece_body = _carry_owners(pieces, piece_body, new_pieces, max(diag, 1e-12))
        res, pieces = cur, new_pieces
    g = sg._analyze_solid(res)
    if splits:
        sg.label_patches(g, g0, records, split_of)
    else:
        for f in g["faces"]:
            f["parent"], f["cell"] = f["id"], None
    _mark_faces(g, res, pieces, piece_body)
    bonds = {}
    for f in g["faces"]:
        if f["interface"] and len(f["bodies"]) >= 2:
            for x in range(len(f["bodies"])):
                for y in range(x + 1, len(f["bodies"])):
                    r = bonds.setdefault((f["bodies"][x], f["bodies"][y]), {"a": f["bodies"][x], "b": f["bodies"][y], "area": 0.0, "faces": []})
                    r["area"] += f["area"]
                    r["faces"].append(f["id"])
    bonds = [bonds[k] for k in sorted(bonds)]
    groups = _groups(n, [(r["a"], r["b"]) for r in bonds])
    vol_of = {}
    for k, p in enumerate(pieces):
        vol_of[piece_body[k]] = vol_of.get(piece_body[k], 0.0) + float(p.volume)
    main = max(groups, key=lambda grp: sum(vol_of.get(i, 0.0) for i in grp))
    floating = [i for grp in groups if grp is not main for i in grp]
    hints = []
    for grp in groups:
        if grp is main:
            continue
        best = None
        for i in grp:
            for j in range(n):
                if j in grp:
                    continue
                try:
                    d = float(solids[i].distance_to(solids[j]))
                except Exception:
                    continue
                if best is None or d < best[0]:
                    best = (d, i, j)
        names = " + ".join(bodies[i][0] for i in grp)
        if best is not None:
            hints.append(f"{names} touches no other body (the nearest is {bodies[best[2]][0]}, {best[0]:.4g} mm from {bodies[best[1]][0]}). "
                         f"Raise the bond distance to at least {best[0] * 1.05:.4g} mm to bond them, or remove the part.")
        else:
            hints.append(f"{names} touches no other body.")
    for (a, b_), v in sorted(overlaps.items()):
        notes.append(f"{bodies[a][0]} and {bodies[b_][0]} overlap (about {v:.4g} mm3 of shared volume); the overlap belongs to {bodies[a][0]}.")
    body_faces = [[] for _ in range(n)]
    for f in g["faces"]:
        if not f["interface"]:
            body_faces[f["body"]].append(f["id"])
    info = []
    for i, (name, _s, mat) in enumerate(bodies):
        info.append({"name": name, "material": body_material(mat), "volume": float(vol_of.get(i, 0.0)), "faces": body_faces[i]})
    psol = []
    for k, p in enumerate(pieces):
        c = p.center(b123.CenterOf.MASS)
        psol.append({"body": piece_body[k], "center": [c.X, c.Y, c.Z], "volume": float(p.volume)})
    g.update({"orig": g0, "split_of": split_of, "notes": notes, "solid": res, "bodies": info, "solids": psol, "bonds": bonds, "groups": groups,
              "floating": floating, "hints": hints, "overlaps": [{"a": a, "b": b_, "volume": v} for (a, b_), v in sorted(overlaps.items())], "tol": tol_used})
    return g


def summary(g):
    """Plain-text lines for the panel: the bonded pairs, then what is wrong."""
    names = [b["name"] for b in g["bodies"]]
    lines = [f"{len(names)} bodies, bond distance {g['tol']:.4g} mm."]
    for r in g["bonds"]:
        lines.append(f"Bonded: {names[r['a']]} - {names[r['b']]} (area {r['area']:.4g} mm2)")
    lines += g["hints"]
    lines += g["notes"]
    return lines


def check(g):
    """The reason why this assembly cannot be solved as it is, or None (parts that touch nothing cannot be held by the supports)."""
    if g.get("floating"):
        names = ", ".join(g["bodies"][i]["name"] for i in g["floating"])
        return (f"These parts are not bonded to the rest: {names}. They would move freely. Raise the bond distance so they touch, or remove them "
                "from the assembly.")
    return None
