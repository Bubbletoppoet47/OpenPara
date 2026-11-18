"""
solid_model.py - the SETUP of a 3D FEA (what the panel edits) and the run that turns it into a result.  No window in it.

setup = {
  "material": {"E": MPa, "nu", "rho": kg/m3, "sy": MPa, "su": MPa},
  "h": element size (mm),
  "supports": [{"mode": "fixed" | "slide" | "bolt", "faces": [face signature]}],
  "loads":    [{"kind": "force", "faces": [sig], "f": [Fx, Fy, Fz]}              total force spread over the faces (N)
              | {"kind": "pressure", "faces": [sig], "p": MPa}                    positive pushes into the part
              | {"kind": "point", "vertex": vertex signature, "f": [Fx, Fy, Fz]}
              | {"kind": "gravity", "g": m/s2, "dir": [x, y, z]}],
  "probe": [x, y, z] or None,
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

import solid_fem as fem
import solid_geom as sg

MODES = {"fixed": "Fixed (all directions)", "slide": "One direction (normal to the face)", "bolt": "Bolt / pin hole (fixed on the hole surface)"}
KINDS = {"force": "Force on faces", "pressure": "Pressure on faces", "point": "Force at a vertex", "gravity": "Gravity"}


def default_setup():
    return {"material": {"E": 200000.0, "nu": 0.3, "rho": 7850.0, "sy": 250.0, "su": 400.0}, "h": 0.0, "supports": [], "loads": [], "probe": None, "splits": []}


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


def resolve(geom, setup):
    """-> {"supports": [{mode, fids, name}], "loads": [...], ...}; fem.FemError for a face that is gone."""
    r = {"material": dict(setup["material"]), "h": float(setup.get("h") or 0.0), "supports": [], "loads": [], "probe": setup.get("probe")}
    for i, s in enumerate(setup["supports"]):
        nm = name_of("Support", i, s)
        fids = _fids(geom, s["faces"], nm)
        r["supports"].append({"mode": s["mode"], "fids": fids, "name": nm})
    for i, l in enumerate(setup["loads"]):
        nm = name_of("Load", i, l)
        it = {k: copy.deepcopy(v) for k, v in l.items() if k not in ("faces", "vertex")}
        it["name"] = nm
        if l["kind"] in ("force", "pressure"):
            it["fids"] = _fids(geom, l["faces"], nm)
        elif l["kind"] == "point":
            vid = sg.match_vertex(geom, l["vertex"])
            if vid is None:
                raise fem.FemError(f"{nm}: its vertex is not in the part any more. Pick it again.")
            it["vid"] = vid
        r["loads"].append(it)
    return r


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


def patch_conditions(setup, geom, fid):
    """Names of the supports and loads that have a patch of the face of `fid` among their faces (they are lost when that face is split again or
    its split is removed)."""
    o = geom.get("orig") or geom
    pid = geom["faces"][fid].get("parent")
    out = []
    for kind, items in (("Support", setup["supports"]), ("Load", setup["loads"])):
        for i, it in enumerate(items):
            if any("cell" in s and sg.match_face(o, s["parent"]) == pid for s in it.get("faces", [])):
                out.append(name_of(kind, i, it))
    return out


def set_split(setup, geom, fid, cols, rows):
    """Cuts the (whole) face of `fid` into cols x rows EQUAL patches in the setup - 1 x 1 removes the split.  Conditions on the patches of that face are
    dropped (those on the whole face stay).  Returns the names of the conditions that were changed or removed."""
    o = geom.get("orig") or geom
    pid = geom["faces"][fid]["parent"]
    i, rec = split_of_face(setup, geom, fid)
    changed = patch_conditions(setup, geom, fid)
    for key in ("supports", "loads"):
        keep = []
        for it in setup[key]:
            if "faces" in it:
                it["faces"] = [s for s in it["faces"] if not ("cell" in s and sg.match_face(o, s["parent"]) == pid)]
                if not it["faces"]:
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


def check_ready(setup):
    """The reason why nothing can run yet, or None."""
    if not setup["supports"]:
        return "Add at least one support."
    if not setup["loads"]:
        return "Add at least one load."
    m = setup["material"]
    if not (m["E"] > 0 and -1 < m["nu"] < 0.5):
        return "The material needs E > 0 and a Poisson's ratio between -1 and 0.5."
    return None


def auto_h(geom):
    return round(geom["diag"] / 14.0, 4)


def mesh_key(geom, h):
    return hashlib.md5(geom["step"]).hexdigest() + f":{h:.8g}"


def get_mesh(geom, h, cache, cancel, progress):
    key = mesh_key(geom, h)
    q = cache.get(key) if cache is not None else None
    if q is None:
        raw = fem.mesh_solid(geom, h, cancel, progress)
        q = fem.quadratic(raw)
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


def run(geom, r, cache=None, cancel=lambda: False, progress=lambda t: None):
    mat = r["material"]
    h = r["h"] or auto_h(geom)
    q = get_mesh(geom, h, cache, cancel, progress)
    nodes, conn = q["nodes"], q["conn"]
    nn = len(nodes)
    cons = []
    names = []
    for s in r["supports"]:
        for fid in s["fids"]:
            if fid not in q["tri6"]:
                raise fem.FemError(f"{s['name']}: the mesh has no elements on that face.")
            nd = np.unique(q["tri6"][fid])
            cons.append((nd, face_normal(q, geom, fid) if s["mode"] == "slide" else None))
            names.append(s["name"])
    force = np.zeros(3 * nn)
    applied = np.zeros(3)
    for l in r["loads"]:
        k = l["kind"]
        if k in ("force", "pressure"):
            tris = [(fid, q["tri6"][fid], q["faces"][fid]) for fid in l["fids"] if fid in q["tri6"]]
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
                for j in (3, 4, 5):                                               # the three mid-edge nodes each carry A/3
                    for c in range(3):
                        np.add.at(force, 3 * t6[:, j] + c, fe[:, c])
                applied += fe.sum(axis=0) * 3
        elif k == "point":
            nd = q["verts"].get(l["vid"])
            if nd is None:
                raise fem.FemError(f"{l['name']}: the mesh has no node at that vertex.")
            f = np.asarray(l["f"], float)
            force[3 * nd:3 * nd + 3] += f
            applied += f
        elif k == "gravity":
            d = np.asarray(l["dir"], float)
            d = d / max(np.linalg.norm(d), 1e-12)
            b = d * float(mat["rho"]) * float(l["g"]) * 1e-9
            fb = fem.body_load(nodes, conn, b)
            force += fb
            applied += fb.reshape(-1, 3).sum(axis=0)
    if not np.any(force):
        raise fem.FemError("The loads are all zero.")
    u, reac, info, K, D = fem.solve(q, mat["E"], mat["nu"], cons, force, cancel, progress)
    progress("stresses")
    vm_el, sig, vol = fem.stresses(nodes, conn, D, u.ravel())
    w = np.zeros(nn)
    acc = np.zeros(nn)
    for j in range(10):
        np.add.at(acc, conn[:, j], vm_el * vol)
        np.add.at(w, conn[:, j], vol)
    vm_node = acc / np.maximum(w, 1e-300)
    s1, s3 = fem.principal(sig)
    total_reac = np.asarray(info["total_reaction"])
    energy = 0.5 * float(force @ u.ravel())
    un = np.linalg.norm(u, axis=1)
    vmax = float(vm_el.max())
    res = {"u": u, "un": un, "vm_node": vm_node, "vm_el": vm_el, "s1": s1, "s3": s3, "nodes": nodes, "conn": conn.astype(np.int32),
           "umax": float(un.max()), "vm_max": vmax, "s1_max": float(s1.max()), "s3_min": float(s3.min()),
           "fos_y": (mat["sy"] / vmax) if vmax > 0 and mat.get("sy") else None, "fos_u": (mat["su"] / vmax) if vmax > 0 and mat.get("su") else None,
           "energy": energy, "reaction": total_reac.tolist(), "applied": applied.tolist(), "support_reactions": _by_support(names, reac),
           "volume": float(vol.sum()), "mass": float(vol.sum()) * float(mat["rho"]) * 1e-9, "n_nodes": nn, "n_tets": len(conn), "h": h,
           "equilibrium": float(np.linalg.norm(total_reac + applied) / max(np.linalg.norm(applied), 1e-12)), "info": info,
           "material": dict(mat)}
    return res


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
