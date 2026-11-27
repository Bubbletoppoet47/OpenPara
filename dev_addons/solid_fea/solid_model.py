"""
solid_model.py - the SETUP of a 3D FEA (what the panel edits) and the run that turns it into a result.  No window in it.

setup = {
  "material": {"E": MPa, "nu", "rho": kg/m3, "sy": MPa, "su": MPa},
  "h": element size (mm, 0 = automatic): of a single part, or of the parts of an assembly that have no size of their own,
  "body_h": {body name: mm}              an ASSEMBLY: the element size of the parts that have one of their own (a blank or missing one gets "h"); the parts are
                                      still meshed as one mesh, so the nodes of the faces they share stay shared (see solid_mesh)
  "supports": [{"mode": "fixed" | "slide" | "bearing" | "disp", "faces": [face signature], "edges": [edge signature], "points": [vertex signature]}],
              a bearing is for the round face(s) of a hole; "edges" and "points" are optional (a support on an edge or a corner is "fixed" or "disp": every node of the
              mesh ALONG the edge, or the node at the corner, is held; a mesh that has no node there is an error, nothing is approximated);
              a "disp" (Displacement) also has "ux", "uy", "uz" (mm): None = free, 0 = held, a number = the faces are moved by exactly that much
  "loads":    [{"kind": "force", "faces": [sig], "f": [Fx, Fy, Fz]}              total force spread over the faces (N)
              | {"kind": "force", "faces": [], "edges": [edge sig], "f": [...]}   total force spread over the length of the edges
              | {"kind": "pressure", "faces": [sig], "p": MPa}                    positive pushes into the part
              | {"kind": "point", "vertex": vertex signature, "f": [Fx, Fy, Fz]}  (several corners: "points": [sig, ...], the force shared equally)
              | {"kind": "gravity", "g": m/s2, "dir": [x, y, z]}],
  "probe": [x, y, z] or None,
  "bond_tol": mm, 0 = automatic        an ASSEMBLY: faces within this distance are bonded (see solid_asm)
  "body_mats": {body name: {"E", "nu", "rho", "sy", "su", "name"}}      an ASSEMBLY: the material of the bodies that were changed from the part's own
  "mesh": {"advanced", "type", "order", "hmin", "growth", "curv", "face_sizes", "follows"}     the advanced mesh options (see solid_mesh); off = the plain automatic mesh
  "adapt": {"on", "crit", "tol", "loops", "cap", "strength", "hmin"}      h-adaptive meshing: solve, refine where the error is large, solve again (see solid_adapt)
  "splits": [{"face": face signature, "cols": n, "rows": m, "u": [x, y, z], "col_sizes": [mm | None, ...], "row_sizes": [...]}]
                                      flat faces cut into patches (see solid_geom.analyze); a size that is None is free (the free ones share the rest equally)
}
A face signature in a support or a load is either a WHOLE face (all its patches when it was split later) or a patch of a split face (see solid_geom.face_sig);
conditions on a whole face and on its patches add up.
`resolve(geom, setup)` turns the signatures into face ids of a (rebuilt) part - a lost face is an error naming the support or load;
`run(geom, resolved, cache, cancel, progress)` meshes (cached), solves and returns the result dict.
"""
import copy
import hashlib

import numpy as np

import solid_adapt as sad
import solid_fem as fem
import solid_geom as sg
import solid_mesh as smesh

MODES = {"fixed": "Fixed (all directions)", "slide": "One direction (normal to the face)", "disp": "Displacement (each direction free, held or moved)",
         "bearing": "Bearing (the hole face is held against moving sideways and along its axis; it can turn)"}
KINDS = {"force": "Force on faces", "pressure": "Pressure on faces", "point": "Force at a vertex", "gravity": "Gravity"}


def default_setup():
    return {"material": {"E": 200000.0, "nu": 0.3, "rho": 7850.0, "sy": 250.0, "su": 400.0}, "h": 0.0, "supports": [], "loads": [], "probe": None, "splits": [],
            "mesh": smesh.default_mesh(), "adapt": sad.default_adapt(), "bond_tol": 0.0, "body_mats": {}, "body_h": {}}


def body_materials(geom, setup):
    """[material dict per body of an assembly]: the one chosen for it in the setup, else the part's own."""
    mine = setup.get("body_mats") or {}
    out = []
    for b in geom["bodies"]:
        m = dict(b["material"])
        m.update({k: v for k, v in (mine.get(b["name"]) or {}).items() if v is not None})
        out.append(m)
    return out


def migrate(setup):
    """Screws, bolts and the contact joint were taken out of the 3D FEA.  An old setup is brought up to date in place: an assembly that was joined by screws is
    now fully bonded (its screws are dropped), a bolt / pin hole support is a fixed support (that is exactly what it was).  -> plain sentences about what
    was changed ([] when nothing was)."""
    notes = []
    screws = len(setup.get("screws") or [])
    if setup.get("joint") == "contact" or screws:
        notes.append("Screws, bolts and contact are not part of the 3D FEA any more: this assembly is solved fully bonded" +
                     (f", and its {screws} screw(s) and bolt(s) were removed." if screws else "."))
    for k in ("joint", "screws", "design"):
        setup.pop(k, None)
    n = 0
    for s_ in setup.get("supports") or []:
        if s_.get("mode") == "bolt":
            s_["mode"] = "fixed"
            n += 1
    if n:
        notes.append(f"{n} bolt / pin hole support(s) are now fixed supports (the same thing).")
    return notes


def name_of(kind, i, item=None):
    return (item or {}).get("name") or f"{kind} {i + 1}"


def _fids(geom, sigs, nm):
    """The face ids of a list of face signatures (a whole face that was split later gives all its patches)."""
    fids = []
    for sig in sigs:
        ids = sg.match_faces(geom, sig)
        if ids is None:
            raise fem.FemError(f"{nm}: its face is not in the part any more (the geometry changed too much, or the face was split again). Pick it again.")
        fids += [i for i in ids if i not in fids]
    return fids


def geo_ids(geom, it, nm):
    """(edge ids, corner ids) of the edges and points of a condition (a support, a load): fem.FemError for one that is gone."""
    eids, vids = [], []
    for sig in it.get("edges") or []:
        e = sg.match_edge(geom, sig)
        if e is None:
            raise fem.FemError(f"{nm}: its edge is not in the part any more (the geometry changed too much). Pick it again.")
        if e not in eids:
            eids.append(e)
    sigs = list(it.get("points") or []) + ([it["vertex"]] if it.get("vertex") else [])
    for sig in sigs:
        v = sg.match_vertex(geom, sig)
        if v is None:
            raise fem.FemError(f"{nm}: its point is not in the part any more. Pick it again.")
        if v not in vids:
            vids.append(v)
    return eids, vids


def where_text(it):
    """'2 faces, 1 edge' for the faces, edges and points a condition acts on (what the lists of conditions say)."""
    parts = []
    for n, word in ((len(it.get("faces") or []), "face"), (len(it.get("edges") or []), "edge"),
                    (len(it.get("points") or []) + (1 if it.get("vertex") else 0), "point")):
        if n:
            parts.append(f"{n} {word}{'' if n == 1 else 's'}")
    return ", ".join(parts) or "nothing"


def edge_nodes(geom, q, eid, name):
    """The mesh nodes along edge `eid` and the share of a line load each carries: (node ids, weights).  fem.FemError when the mesh has no nodes along the edge or does not
    follow all of it - nothing is approximated."""
    c = sg.edge_chain(geom, eid, q["nodes"], q.get("n_corner") or len(q["nodes"]), q.get("order", 2))
    if not len(c["nodes"]):
        raise fem.FemError(f"{name}: this mesh has no nodes along that edge (edge {eid + 1}), so nothing can be put on it. Use a face, or a mesh type with nodes along the edges.")
    if c["cover"] < 0.98 or not c["ok"]:
        raise fem.FemError(f"{name}: the mesh does not follow all of edge {eid + 1} (its nodes cover {c['cover']:.0%} of it). Use a face, or a finer mesh.")
    return c["nodes"], c["w"]


def resolve(geom, setup):
    """-> {"supports": [{mode, fids, name}], "loads": [...], ...}; fem.FemError for a face that is gone."""
    r = {"material": dict(setup["material"]), "h": float(setup.get("h") or 0.0), "supports": [], "loads": [], "probe": setup.get("probe"),
         "mesh": smesh.resolve(geom, setup, float(setup.get("h") or 0.0) or auto_h(geom))}
    r["adapt"] = sad.resolve(geom, setup)                                    # None = a single mesh
    if geom.get("bodies"):
        r["materials"] = body_materials(geom, setup)
        r["material"] = dict(r["materials"][0])
    for i, s in enumerate(setup["supports"]):
        nm = name_of("Support", i, s)
        fids = _fids(geom, s.get("faces") or [], nm)
        eids, vids = geo_ids(geom, s, nm)
        if (eids or vids) and s["mode"] not in ("fixed", "disp"):
            raise fem.FemError(f"{nm}: {MODES[s['mode']].split(' (')[0]} needs a face. On an edge or a point use Fixed or Displacement.")
        if not (fids or eids or vids):
            raise fem.FemError(f"{nm}: it has no face, edge or point.")
        if s["mode"] == "bearing":
            for f in fids:
                if not geom["faces"][f].get("cyl"):
                    raise fem.FemError(f"{nm}: a bearing needs the round (cylindrical) face of a hole, and that face is a {geom['faces'][f]['kind']}.")
        it = {"mode": s["mode"], "fids": fids, "name": nm, "eids": eids, "vids": vids}
        if s["mode"] == "disp":
            it.update({k: (None if s.get(k) is None else float(s[k])) for k in ("ux", "uy", "uz")})
            if all(it[k] is None for k in ("ux", "uy", "uz")):
                raise fem.FemError(f"{nm}: every direction is blank, so this support holds nothing. Type 0 to hold a direction, or a number to move it.")
        r["supports"].append(it)
    for i, l in enumerate(setup["loads"]):
        nm = name_of("Load", i, l)
        it = {k: copy.deepcopy(v) for k, v in l.items() if k not in ("faces", "vertex", "edges", "points")}
        it["name"] = nm
        if l["kind"] in ("force", "pressure"):
            it["fids"] = _fids(geom, l.get("faces") or [], nm)
            it["eids"] = geo_ids(geom, l, nm)[0]
            if l["kind"] == "pressure" and it["eids"]:
                raise fem.FemError(f"{nm}: a pressure acts on faces, not on an edge.")
            if it["fids"] and it["eids"]:
                raise fem.FemError(f"{nm}: a force acts on faces or on edges, not on both. Make one load for the faces and one for the edges.")
            if not (it["fids"] or it["eids"]):
                raise fem.FemError(f"{nm}: it has no face or edge.")
        elif l["kind"] == "point":
            vids = geo_ids(geom, l, nm)[1]
            if not vids:
                raise fem.FemError(f"{nm}: its vertex is not in the part any more. Pick it again.")
            it["vids"] = vids
            it["vid"] = vids[0]
        r["loads"].append(it)
    return r


def thin_parts(geom, h, sizes=None):
    """{body index: text} for the parts whose thickness (about twice the volume over the surface) is below 1.5 element sizes: a coarse mesh through a thin
    sheet is poor.  `sizes` = the element size of every part when they differ (see solid_fem.element_sizes), else `h` is every part's size."""
    out = {}
    for i, b in enumerate(geom.get("bodies") or ()):
        hb = sizes[i] if sizes is not None and i < len(sizes) else h
        area = sum(f["area"] for f in geom["faces"] if i in f["bodies"])
        t = 2.0 * b["volume"] / max(area, 1e-12)
        if t > 0 and hb > 1.5 * t:
            out[i] = (f"{b['name']} is about {t:.3g} mm thick but its element size is {hb:.3g} mm: use an element size of {t:.2g} mm or less (or an advanced "
                      "local size) so that the sheet has several elements through its thickness.")
    return out


def thin_notes(geom, h, sizes=None):
    """The texts of thin_parts, in the order of the parts."""
    return [t for _i, t in sorted(thin_parts(geom, h, sizes).items())]


# ------------------------------------------------------------------------------------------------------------------------ splitting faces
def split_of_face(setup, geom, fid):
    """(index in setup["splits"], record) of the split that made face `fid` of geom (a patch), or (None, None)."""
    o = geom.get("orig") or geom
    pid = geom["faces"][fid].get("parent")
    if pid is None:
        return None, None
    for i, s in enumerate(setup.get("splits") or []):
        if sg.match_face(o, s["face"]) == pid:
            return i, s
    return None, None


CONDITION_KINDS = (("Support", "supports"), ("Load", "loads"))          # (name, key in the setup) of the lists of conditions that act on faces; another window passes its own


def patch_conditions(setup, geom, fid, kinds=CONDITION_KINDS):
    """Names of the supports and loads that have a patch of the face of `fid` among their faces (they are lost when that face is split again or
    its split is removed).  `kinds` = the lists of conditions of the setup to look in: (name, key) ..."""
    o = geom.get("orig") or geom
    pid = geom["faces"][fid].get("parent")
    out = []
    for kind, items in ((k, setup.get(key) or []) for k, key in kinds):
        for i, it in enumerate(items):
            if any("cell" in s and sg.match_face(o, s["parent"]) == pid for s in it.get("faces", [])):
                out.append(name_of(kind, i, it))
    return out


def set_split(setup, geom, fid, cols, rows, kinds=CONDITION_KINDS):
    """Cuts the (whole) face of `fid` into cols x rows EQUAL patches in the setup - 1 x 1 removes the split.  Conditions on the patches of that face are
    dropped (those on the whole face stay).  Returns the names of the conditions that were changed or removed."""
    o = geom.get("orig") or geom
    pid = geom["faces"][fid]["parent"]
    i, rec = split_of_face(setup, geom, fid)
    changed = patch_conditions(setup, geom, fid, kinds)
    for key in [k for _n, k in kinds]:
        keep = []
        for it in setup.get(key) or []:
            if "faces" in it:
                had = bool(it["faces"])
                it["faces"] = [s for s in it["faces"] if not ("cell" in s and sg.match_face(o, s["parent"]) == pid)]
                if had and not it["faces"] and not (it.get("edges") or it.get("points")):
                    continue
            keep.append(it)
        setup[key] = keep
    splits = [s for k, s in enumerate(setup.get("splits") or []) if k != i]
    if cols * rows > 1:
        splits.append({"face": sg._base_sig(o["faces"][pid]), "cols": int(cols), "rows": int(rows), "u": (geom.get("split_of") or {}).get(pid, {}).get("u"),
                       "col_sizes": [None] * int(cols), "row_sizes": [None] * int(rows)})
    setup["splits"] = splits
    return changed


def set_sizes(setup, geom, fid, col_sizes, row_sizes):
    """Fixes the size (mm) of some columns / rows of the split of the face of `fid` (None = free: the free ones share the rest equally).  The number of
    columns and rows stays, so the supports and loads on its patches stay on their patches.  Raises sg.GeomError when the sizes do not fit the face."""
    i, rec = split_of_face(setup, geom, fid)
    pid = geom["faces"][fid].get("parent")
    info = (geom.get("split_of") or {}).get(pid)
    if rec is None or info is None:
        raise sg.GeomError("That face is not split.")
    cs = [None if s is None else float(s) for s in col_sizes]
    rs = [None if s is None else float(s) for s in row_sizes]
    sg.solve_sizes(info["len_u"], rec["cols"], cs)                 # raises when they do not fit
    sg.solve_sizes(info["len_v"], rec["rows"], rs)
    rec["col_sizes"], rec["row_sizes"] = cs, rs
    return rec


def check_ready(setup, geom=None, thermal=False, fluid=False):
    """The reason why nothing can run yet, or None.  `geom` (when given and an assembly) also checks every body's material and that the bodies hold together.
    thermal=True: a temperature is a load (a Coupled Physics solve), so the setup needs none of its own; so does fluid=True (the pressure of a flow is the load)."""
    if not setup["supports"]:
        return "Add at least one support."
    if not (thermal or fluid) and not setup["loads"] and not any(s_.get("mode") == "disp" and any(s_.get(k) not in (None, 0, 0.0) for k in ("ux", "uy", "uz")) for s_ in setup["supports"]):
        return "Add at least one load (or a Displacement that moves a face)."
    if geom is not None and geom.get("bodies"):
        import solid_asm
        why = solid_asm.check(geom)
        if why:
            return why
        for b, m in zip(geom["bodies"], body_materials(geom, setup)):
            if not (m["E"] > 0 and -1 < m["nu"] < 0.5):
                return f"{b['name']}: the material needs E > 0 and a Poisson's ratio between -1 and 0.5."
        return None
    m = setup["material"]
    if not (m["E"] > 0 and -1 < m["nu"] < 0.5):
        return "The material needs E > 0 and a Poisson's ratio between -1 and 0.5."
    return None


def auto_h(geom):
    return round(geom["diag"] / 14.0, 4)


def mesh_key(geom, h, opts=None):
    """The cache key of a mesh: the part, the element size and (for the advanced options, see solid_mesh.resolve) the options.  The plain automatic mesh
    has the key it always had."""
    return hashlib.md5(geom["step"]).hexdigest() + f":{h:.8g}" + smesh.key_text(opts)


def get_mesh(geom, h, cache, cancel, progress, opts=None):
    """The mesh (cached): quadratic tetrahedra, or linear ones when opts["order"] == 1; with opts["type"] == "hexdom" a hex-dominant mesh (hexahedra and
    pyramids besides the tetrahedra; where that is not possible q["hexdom_note"] says why and the mesh is tetrahedra).  It carries its quality report:
    q["quality"]."""
    key = mesh_key(geom, h, opts)
    q = cache.get(key) if cache is not None else None
    if q is None:
        raw = fem.mesh_solid(geom, h, cancel, progress, opts)
        q = fem.linear(raw) if opts and opts["order"] == 1 else fem.quadratic(raw)
        q["quality"] = smesh.quality(q)
        if cache is not None:
            cache[key] = q
    return q


def face_normal(q, geom, fid):
    """Area weighted outward normal of a face of the mesh."""
    tri = q["faces"][fid]
    nv, area = fem.outward_normals(q, tri)
    n = (nv * area[:, None]).sum(axis=0)
    ln = np.linalg.norm(n)
    return n / ln if ln > 1e-12 else np.asarray(geom["faces"][fid]["normal"], float)


def run(geom, r, cache=None, cancel=lambda: False, progress=lambda t: None, thermal=None, fluid=None):
    """thermal: None, or {"T": ...} for the mesh, or a function of the mesh q that gives that (the mesh is made inside, so the temperature is looked up on its nodes).
    fluid: None, or {"fids": [...], "p": ...} (see solve_mesh), or a function of the mesh q that gives that (the pressure of a flow, looked up on the nodes of the mesh)."""
    h = r["h"] or auto_h(geom)
    if r.get("adapt"):                                                         # solve, refine, solve again (solid_adapt)
        if thermal is not None:
            raise fem.FemError("The adaptive mesh loop does not include a temperature yet: untick 'Adaptive mesh (h)' for a thermal-stress solve.")
        if fluid is not None:
            raise fem.FemError("The adaptive mesh loop does not include the pressure of a fluid yet: untick 'Adaptive mesh (h)' for a solve with a flow.")
        return sad.run(geom, r, h, cache, cancel, progress, get_mesh, solve_mesh)
    q = get_mesh(geom, h, cache, cancel, progress, r.get("mesh"))
    if callable(thermal):
        thermal = thermal(q)
    if callable(fluid):
        fluid = fluid(q)
    return solve_mesh(geom, r, h, q, cancel, progress, thermal, fluid)


def solve_mesh(geom, r, h, q, cancel=lambda: False, progress=lambda t: None, thermal=None, fluid=None):
    """Solves the setup `r` on the mesh `q` (element size `h`) and returns the result dict.
    thermal = {"T": the temperature at every node of the mesh q (kelvin)}: the body is heated or cooled to it from the material's reference temperature
    (material["Tref"], 20 degC when missing) and expands by material["alpha"] (1/K, needed; an assembly: each body's own).  It is a load of its own: no other load is then needed.
    fluid = {"fids": [face ids], "p": the pressure at every node of the mesh q in MPa}: the pressure of a flow, pushing into the part on those faces (the mean of its three corner
    values on every surface triangle; the friction of the flow is not in it).  It is a load of its own too."""
    mat = r["material"]
    sizes = fem.element_sizes(geom, h, r.get("mesh"))                           # the element size of every part (one entry for a single part)
    mats = r.get("materials") if geom.get("bodies") else None
    nodes, conn, groups = q["nodes"], q["conn"], q["groups"]
    if mats:                                                                   # an assembly: every body's elements carry its own material
        groups = [dict(g, mat=(mats[g["body"]]["E"], mats[g["body"]]["nu"]), alpha=mats[g["body"]].get("alpha"), Tref=mats[g["body"]].get("Tref")) for g in groups]
        q = dict(q, groups=groups)
    nn = len(nodes)
    ftri = q["ftri"]                                                           # the nodes of the triangles of every face: 6 per triangle (quadratic) or 3
    load_cols = (3, 4, 5) if q["order"] == 2 else (0, 1, 2)                    # the nodes that carry a share of a face load: the mid-edge nodes, or the corners
    cons = []
    names = []
    for s in r["supports"]:
        for fid in s["fids"]:
            if fid not in ftri:
                raise fem.FemError(f"{s['name']}: the mesh has no elements on that face.")
            nd = np.unique(ftri[fid])
            if s["mode"] == "bearing":
                cy = geom["faces"][fid]["cyl"]
                cons.append((nd, {"bearing": (cy["origin"], cy["axis"])}))
            elif s["mode"] == "disp":
                cons.append((nd, {"disp": (s["ux"], s["uy"], s["uz"])}))
            else:
                cons.append((nd, face_normal(q, geom, fid) if s["mode"] == "slide" else None))
            names.append(s["name"])
        held = {"disp": (s.get("ux"), s.get("uy"), s.get("uz"))} if s["mode"] == "disp" else None
        for eid in s.get("eids") or []:                                          # every node of the mesh along the edge
            cons.append((edge_nodes(geom, q, eid, s["name"])[0], held))
            names.append(s["name"])
        for vid in s.get("vids") or []:
            nd = q["verts"].get(vid)
            if nd is None:
                raise fem.FemError(f"{s['name']}: the mesh has no node at that point (point {vid + 1}).")
            cons.append((np.array([int(nd)]), held))
            names.append(s["name"])
    force = np.zeros(3 * nn)
    applied = np.zeros(3)
    for l in r["loads"]:
        k = l["kind"]
        if k == "force" and l.get("eids"):                                       # a force along edges: the total is shared by the length each node carries
            lens = [float(geom["edges"][e]["length"]) for e in l["eids"]]
            f = np.asarray(l["f"], float)
            for e, le in zip(l["eids"], lens):
                nd, w = edge_nodes(geom, q, e, l["name"])
                share = f * (le / max(sum(lens), 1e-300))
                for c in range(3):
                    np.add.at(force, 3 * nd + c, w * share[c])
            applied += f
            continue
        if k in ("force", "pressure"):
            tris = [(fid, ftri[fid], q["faces"][fid]) for fid in l["fids"] if fid in ftri]
            if not tris:
                raise fem.FemError(f"{l['name']}: the mesh has no elements on that face.")
            parts = []
            for fid, t6, t3 in tris:
                nv, area = fem.outward_normals(q, t3)
                parts.append((t6, nv, area))
            total = sum(float(a.sum()) for _t, _n, a in parts)
            for t6, nv, area in parts:
                if k == "pressure":
                    trac = -float(l["p"]) * nv                                     # (nt, 3) traction N/mm2, into the part for p > 0
                else:
                    trac = np.tile(np.asarray(l["f"], float) / total, (len(area), 1))
                fe = trac * (area / 3.0)[:, None]
                for j in load_cols:                                               # the three mid-edge nodes (corners of a linear mesh) each carry A/3
                    for c in range(3):
                        np.add.at(force, 3 * t6[:, j] + c, fe[:, c])
                applied += fe.sum(axis=0) * 3
        elif k == "point":
            vids = l.get("vids") or [l["vid"]]
            f = np.asarray(l["f"], float) / len(vids)                          # several corners share the force equally
            for vid in vids:
                nd = q["verts"].get(vid)
                if nd is None:
                    raise fem.FemError(f"{l['name']}: the mesh has no node at that point (point {vid + 1}).")
                force[3 * nd:3 * nd + 3] += f
            applied += np.asarray(l["f"], float)
        elif k == "gravity":
            d = np.asarray(l["dir"], float)
            d = d / max(np.linalg.norm(d), 1e-12)
            if mats:
                b = lambda grp, d=d, gv=float(l["g"]): d * float(mats[grp["body"]]["rho"]) * gv * 1e-9
            else:
                b = d * float(mat["rho"]) * float(l["g"]) * 1e-9
            fb = fem.body_load(nodes, groups, b)
            force += fb
            applied += fb.reshape(-1, 3).sum(axis=0)
    fl_sum = None
    if fluid is not None:
        pn = np.asarray(fluid["p"], float)
        if pn.shape != (nn,):
            raise fem.FemError("The pressure of the fluid is not given at the nodes of this mesh.")
        f_fl, p_all = np.zeros(3), []
        for fid in fluid["fids"]:
            if fid not in ftri:
                raise fem.FemError("The mesh has no elements on a face that the fluid loads.")
            t6, t3 = ftri[fid], q["faces"][fid]
            nv, area = fem.outward_normals(q, t3)
            p_el = pn[np.asarray(t3)].mean(axis=1)
            fe = (-p_el[:, None] * nv) * (area / 3.0)[:, None]                  # (nt, 3): into the part for p > 0, a third of the triangle's force per node
            for j in load_cols:
                for c in range(3):
                    np.add.at(force, 3 * t6[:, j] + c, fe[:, c])
            applied += fe.sum(axis=0) * 3
            f_fl += fe.sum(axis=0) * 3
            p_all.append(p_el)
        pa = np.concatenate(p_all) if p_all else np.zeros(1)
        fl_sum = {"force": f_fl.tolist(), "faces": [int(f) for f in fluid["fids"]], "p_min": float(pa.min()), "p_max": float(pa.max())}
    imposed = any(s["mode"] == "disp" and any(s[k] not in (None, 0.0) for k in ("ux", "uy", "uz")) for s in r["supports"])      # a movement is a load too
    th, fth = None, None
    if thermal is not None:
        th = {"T": np.asarray(thermal["T"], float), "alpha": mat.get("alpha"), "Tref": mat.get("Tref", 293.15)}
        fth = fem.thermal_load(nodes, groups, mat["E"], mat["nu"], th)
        force = force + fth                                                         # (an internal load: it adds nothing to the applied total)
    if not np.any(force) and not imposed and th is None and fl_sum is None:
        raise fem.FemError("The loads are all zero.")
    u, reac, info, K, D = fem.solve(q, mat["E"], mat["nu"], cons, force, cancel, progress)
    progress("stresses")
    fem._stage(progress, "stress", float(sum(len(g["conn"]) for g in groups)))
    if th is not None:
        vm_el, sig, vol, en_th = fem.stresses(nodes, groups, D, u.ravel(), th, True)
    else:
        vm_el, sig, vol = fem.stresses(nodes, groups, D, u.ravel())
    w = np.zeros(nn)
    acc = np.zeros(nn)
    base = 0
    for g in groups:
        gc = g["conn"]
        sl = slice(base, base + len(gc))
        for j in range(gc.shape[1]):
            np.add.at(acc, gc[:, j], (vm_el * vol)[sl])
            np.add.at(w, gc[:, j], vol[sl])
        base += len(gc)
    vm_node = acc / np.maximum(w, 1e-300)
    per_body, sy_node = None, None
    if mats:
        per_body, sy_node = _per_body(geom, mats, groups, vm_el, vol, nn)
    s1, s3 = fem.principal(sig)
    total_reac = np.asarray(info["total_reaction"])
    energy = 0.5 * float(u.ravel() @ (K @ u.ravel())) if imposed else 0.5 * float(force @ u.ravel())      # (a displacement does the work, not only the loads)
    if th is not None:
        energy = en_th                                                          # half u.f would count the thermal strain too: the elastic energy is the strain minus the thermal strain
    un = np.linalg.norm(u, axis=1)
    vmax = float(vm_el.max())
    fos_y = (mat["sy"] / vmax) if vmax > 0 and mat.get("sy") else None
    fos_u = (mat["su"] / vmax) if vmax > 0 and mat.get("su") else None
    if per_body is not None:                                                  # the weakest body decides
        ys = [b["fos_y"] for b in per_body if b["fos_y"] is not None]
        us = [b["fos_u"] for b in per_body if b["fos_u"] is not None]
        fos_y, fos_u = (min(ys) if ys else None), (min(us) if us else None)
    res = {"u": u, "un": un, "vm_node": vm_node, "vm_el": vm_el, "s1": s1, "s3": s3, "nodes": nodes, "conn": conn.astype(np.int32),
           "umax": float(un.max()), "vm_max": vmax, "s1_max": float(s1.max()), "s3_min": float(s3.min()),
           "fos_y": fos_y, "fos_u": fos_u,
           "energy": energy, "reaction": total_reac.tolist(), "applied": applied.tolist(), "support_reactions": _by_support(names, reac),
           "volume": float(vol.sum()), "mass": (sum(b["mass"] for b in per_body) if per_body is not None else float(vol.sum()) * float(mat["rho"]) * 1e-9), "n_nodes": nn, "n_tets": len(conn), "n_elements": int(len(vm_el)), "h": h,
           "counts": {"tets": len(conn), "hexes": int(len(q.get("hexes", ()))), "pyramids": int(len(q.get("pyrs", ())))}, "viewcells": q.get("viewcells"),
           "hexdom_note": q.get("hexdom_note"), "tet_body": q.get("tet_body"),
           "order": int(q["order"]), "quality": q.get("quality"), "mesh_opts": r.get("mesh"),
           "equilibrium": float(np.linalg.norm(total_reac + applied) / max(np.linalg.norm(applied), (float(np.linalg.norm(reac, axis=1).sum()) if imposed else 0.0), (float(np.linalg.norm(fth)) if th is not None else 0.0), 1e-12)),
           "info": info, "thermal": (None if th is None else _thermal_summary(th, mat, mats)), "fluid": fl_sum,
           "material": dict(mat), "surface": {fid: np.asarray(t, np.int32) for fid, t in (q.get("ftri") or q.get("faces") or {}).items()}}
    if per_body is not None:
        res.update({"bodies": per_body, "sy_node": sy_node, "material": dict(mat, sy=0.0, su=0.0), "bond_tol": geom.get("tol"),
                    "bonds": [{"a": geom["bodies"][b["a"]]["name"], "b": geom["bodies"][b["b"]]["name"], "area": b["area"]} for b in geom["bonds"]]})
        res["notes"] = thin_notes(geom, h, sizes)
        res["part_sizes"] = [{"name": b["name"], "h": float(sizes[i])} for i, b in enumerate(geom["bodies"])]
    return res


def _thermal_summary(th, mat, mats):
    """What a thermal-stress result says about its temperature: the range of the field and the expansion data the bodies used (kelvin, 1 / kelvin)."""
    out = {"T_min": float(th["T"].min()), "T_max": float(th["T"].max())}
    ms = list(mats) if mats else [mat]
    al = [float(m["alpha"]) for m in ms if m.get("alpha") is not None]
    tr = [float(m.get("Tref") if m.get("Tref") is not None else 293.15) for m in ms if m.get("alpha") is not None]
    if al:
        out.update(alpha_min=min(al), alpha_max=max(al), Tref_min=min(tr), Tref_max=max(tr))
    return out


def _per_body(geom, mats, groups, vm_el, vol, nn):
    """([one record per body: name, material, volume, mass, von Mises maximum, safety factors], yield strength per node (0 = none; the smallest of the
    bodies around a node on an interface))."""
    n = len(mats)
    vmx, vv = np.zeros(n), np.zeros(n)
    sy_node = np.full(nn, np.inf)
    base = 0
    for g in groups:
        ne = len(g["conn"])
        b = g["body"]
        vmx[b] = max(vmx[b], float(vm_el[base:base + ne].max())) if ne else vmx[b]
        vv[b] += float(vol[base:base + ne].sum())
        sy = float(mats[b].get("sy") or 0.0)
        nd = np.unique(g["conn"])
        sy_node[nd] = np.minimum(sy_node[nd], sy if sy > 0 else np.inf)
        base += ne
    sy_node[~np.isfinite(sy_node)] = 0.0
    out = []
    for i, m in enumerate(mats):
        sy, su = float(m.get("sy") or 0.0), float(m.get("su") or 0.0)
        out.append({"name": geom["bodies"][i]["name"], "material": dict(m), "volume": float(vv[i]), "mass": float(vv[i]) * float(m["rho"]) * 1e-9,
                    "vm_max": float(vmx[i]), "fos_y": (sy / vmx[i]) if vmx[i] > 0 and sy > 0 else None, "fos_u": (su / vmx[i]) if vmx[i] > 0 and su > 0 else None})
    return out, sy_node


def _by_support(names, reac):
    """[(support name, reaction)]: the reactions of all the faces (patches) of one support added up, in the order of the supports."""
    out = {}
    for n, r_ in zip(names, reac):
        out[n] = out.get(n, 0.0) + np.asarray(r_, float)
    return [(n, v.tolist()) for n, v in out.items()]


def probe(res, point):
    """The node nearest to a point: (node index, distance, |u|, von Mises)."""
    d = np.linalg.norm(res["nodes"] - np.asarray(point, float), axis=1)
    i = int(np.argmin(d))
    return i, float(d[i]), float(res["un"][i]), float(res["vm_node"][i])
