"""cfd3d_model.py - the SETUP of a 3D Fluid Flow analysis (what the panel edits) and the run that turns it into a result.  No window in it.

A 3D Fluid Flow analysis is the air (or water) flowing AROUND a part: the part is cut out of a box (the "domain", a wind tunnel round it), the fluid enters on
one face of the box, leaves on the opposite one, and the four sides of the box are slip planes (they do not hold the flow back).  The faces of the part are walls:
the fluid sticks to them.  The geometry is the 3D FEA's (solid_base / solid_geom: the part, its faces); the mesh is the fluid's own (cfd3d_mesh.air_domain).

setup = {
  ... the keys of solid_base.SolidBase.new_setup(): "dims", "splits", "bond_tol", "body_mats", "body_h", "h", "mesh" ...,
  "fluid": {"name", "rho": kg/m3, "mu": Pa s, "k": W/(m K), "cp": J/(kg K)},
  "flow":  {"speed": m/s, "dir": "+x" | "-x" | "+y" | "-y" | "+z" | "-z" (the way the fluid flows), "heat": True when the temperature is solved too, "T_in": K},
  "domain": {"up": n, "down": n, "side": n (the box margins in lengths of the part: its largest size), "h_far": mm (0 = automatic)},
  "temps":  [{"name", "faces": [face signature], "T": K}]            wall temperature
  "fluxes": [{"name", "faces", "q": W/m2}]                           heat flux INTO the fluid
  "ins":    [{"name", "faces"}]                                      adiabatic wall (nothing is added; it makes the choice visible)
  "probe": [x, y, z] or None
}
`h` of the setup is the element size on the part (mm, 0 = automatic).  Everything stored is SI (and kelvin); the units of File > Units only change what is shown.
`resolve(geom, setup)` turns the setup into what `run` takes; the result is the dict of cfd3d_flow.solve_flow with the pieces the window needs added.
"""
import copy
import hashlib

import numpy as np

import cfd3d_flow as cf
import cfd3d_mesh as cmesh
import solid_fem as fem
import solid_mesh as smesh
import solid_model as sm

CONDITION_KINDS = (("Wall temperature", "temps"), ("Wall heat flux", "fluxes"), ("Adiabatic wall", "ins"))
KEYS = tuple(k for _n, k in CONDITION_KINDS)
NAMES = dict((k, n) for n, k in CONDITION_KINDS)
VALUES = {"temps": ("T",), "fluxes": ("q",), "ins": ()}
DIRS = {"+x": (1.0, 0.0, 0.0), "-x": (-1.0, 0.0, 0.0), "+y": (0.0, 1.0, 0.0), "-y": (0.0, -1.0, 0.0), "+z": (0.0, 0.0, 1.0), "-z": (0.0, 0.0, -1.0)}
DIR_TEXT = {"+x": "toward +X", "-x": "toward -X", "+y": "toward +Y", "-y": "toward -Y", "+z": "toward +Z", "-z": "toward -Z"}
BOX = ("x-", "x+", "y-", "y+", "z-", "z+")
NEAR_DIVISOR = 16.0                 # the automatic element size on the part: its largest size / this
FAR_DIVISOR = 7.0                   # the automatic element size far from the part: the longest side of the box / this
RE_STEADY = 150.0                   # above this Reynolds number the flow past a blunt body is usually not steady any more (it sheds vortices)
BLOCKAGE_WARN = 0.10                # the share of the cross-section of the box that the part covers, above which the box walls are felt
MAX_NODES_WARN = 150000
ENERGY_OK = 0.10                    # the energy mismatch (of the larger of the two heats) below which the balance is called closed
ENERGY_COARSE = 0.35                # above it the mesh near the part is far too coarse for the temperature (or something is wrong)
NODE_VOLUME = 0.8                   # the volume one node takes in a tetrahedral mesh of element size h, in h3 (fitted to real meshes, see estimate_nodes)


def default_fluid():
    import physics_cfd as pc
    name = "Air 20 C"
    rho, mu = pc.FLUIDS[name]
    k, cp = pc.FLUID_HEAT[name]
    return {"name": name, "rho": float(rho), "mu": float(mu), "k": float(k), "cp": float(cp)}


def default_setup():
    s = {"dims": {}, "splits": [], "bond_tol": 0.0, "body_mats": {}, "body_h": {}, "h": 0.0, "mesh": smesh.default_mesh(), "fluid": default_fluid()}
    s["mesh"]["order"] = 1
    s["flow"] = {"speed": 0.05, "dir": "+x", "heat": False, "T_in": 293.15}
    s["domain"] = {"up": 1.0, "down": 3.0, "side": 1.5, "h_far": 0.0}
    for k in KEYS:
        s[k] = []
    s["probe"] = None
    return s


def part_size(geom):
    """The largest size of the part along an axis (mm): what the box margins and the automatic element sizes are measured in."""
    bb = np.asarray(geom["bbox"], float)
    return float(max((bb[1] - bb[0]).max(), 1e-9))


def box_roles(direction):
    """-> (inlet patch, outlet patch, [slip patches]) of the box for a flow direction."""
    ax = "xyz".index(direction[1])
    plus = direction[0] == "+"
    inlet = "xyz"[ax] + ("-" if plus else "+")
    outlet = "xyz"[ax] + ("+" if plus else "-")
    return inlet, outlet, [n for n in BOX if n not in (inlet, outlet)]


def domain_box(geom, setup):
    """-> (lo, hi) in mm: the part's bounding box with the margins of the domain (upstream, downstream and sideways, in lengths of the part)."""
    dom, flow = setup["domain"], setup["flow"]
    bb = np.asarray(geom["bbox"], float)
    L = part_size(geom)
    lo = bb[0] - float(dom["side"]) * L
    hi = bb[1] + float(dom["side"]) * L
    ax = "xyz".index(flow["dir"][1])
    up, down = float(dom["up"]) * L, float(dom["down"]) * L
    if flow["dir"][0] == "+":
        lo[ax], hi[ax] = bb[0][ax] - up, bb[1][ax] + down
    else:
        lo[ax], hi[ax] = bb[0][ax] - down, bb[1][ax] + up
    return lo, hi


def sizes_mm(geom, setup):
    """-> (the element size on the part, the one far from it), mm: typed, or automatic."""
    L = part_size(geom)
    h_near = float(setup.get("h") or 0.0) or round(L / NEAR_DIVISOR, 4)
    lo, hi = domain_box(geom, setup)
    h_far = float(setup["domain"].get("h_far") or 0.0) or round(float((hi - lo).max()) / FAR_DIVISOR, 4)
    return h_near, max(h_far, h_near)


def frontal_area(geom, setup):
    """The area (mm2) of the shadow of the part's bounding box across the flow, and the share of the domain's cross-section it covers (the blockage)."""
    bb = np.asarray(geom["bbox"], float)
    lo, hi = domain_box(geom, setup)
    ax = "xyz".index(setup["flow"]["dir"][1])
    keep = [i for i in range(3) if i != ax]
    a = float(np.prod((bb[1] - bb[0])[keep]))
    A = float(np.prod((hi - lo)[keep]))
    return a, a / max(A, 1e-12)


def estimate_nodes(geom, setup):
    """A rough number of nodes of the air mesh (for the progress bar and a warning before a huge mesh is made): the element size grows from the size on the part
    to the one far away by the growth rate, with the distance from the part (the size field of the mesher), and a tetrahedral mesh has about one node per 0.8 h3.
    The volume within a distance d of the part is that of a sphere with the part's surface area (Steiner's formula).  Checked against real meshes of a cube, a bar and
    a block with a hole: within about 16 % on the cases tried."""
    h_near, h_far = sizes_mm(geom, setup)
    lo, hi = domain_box(geom, setup)
    mo = setup.get("mesh") or {}
    g = (float(mo.get("growth") or 1.3) if mo.get("advanced") else 1.3) - 1.0
    area = float(sum(f["area"] for f in geom["faces"]))
    vol_part = float(geom.get("volume") or 0.0)
    d_max = max(h_far - h_near, 0.0) / max(g, 1e-6)
    mean_curv = 4.0 * np.pi * np.sqrt(area / (4.0 * np.pi))
    d = np.linspace(0.0, d_max, 400)
    shell = area + 2.0 * mean_curv * d + 4.0 * np.pi * d * d
    near = float(np.trapezoid(shell / (NODE_VOLUME * (h_near + g * d) ** 3), d))
    v_near = vol_part + area * d_max + mean_curv * d_max ** 2 + 4.0 * np.pi / 3.0 * d_max ** 3
    far = max(float(np.prod(hi - lo)) - v_near, 0.0) / (NODE_VOLUME * h_far ** 3)
    return int(near + far + 100)


# ---------------------------------------------------------------------------------------------------------------------------- is it ready, and what to run
def fluid_problem(f):
    try:
        if not float(f["rho"]) > 0:
            return "The density of the fluid must be greater than zero."
        if not float(f["mu"]) > 0:
            return "The viscosity of the fluid must be greater than zero."
    except (KeyError, TypeError, ValueError):
        return "The fluid needs a density and a viscosity."
    return None


def check_ready(setup, geom=None):
    """The reason why nothing can run yet, or None."""
    if geom is not None and geom.get("bodies"):
        return "3D Fluid Flow takes a single part for now: an assembly has no one solid to cut out of the fluid. Wire a Part into the Geometry cell."
    why = fluid_problem(setup["fluid"])
    if why:
        return why
    fl, dom = setup["flow"], setup["domain"]
    if not float(fl.get("speed") or 0) > 0:
        return "The speed of the flow must be greater than zero."
    if fl.get("dir") not in DIRS:
        return "Choose the direction the fluid flows in."
    if any(float(dom.get(k) or 0) < 0 for k in ("up", "down", "side", "h_far")):
        return "The margins of the domain cannot be negative."
    if not (float(dom.get("up") or 0) > 0 and float(dom.get("down") or 0) > 0 and float(dom.get("side") or 0) > 0):
        return "The domain needs room upstream, downstream and at the sides of the part (a margin of at least a few tenths of its size)."
    if fl.get("heat"):
        f = setup["fluid"]
        if not (float(f.get("k") or 0) > 0 and float(f.get("cp") or 0) > 0):
            return "The temperature needs the conductivity and the specific heat of the fluid."
        if not float(fl.get("T_in") or 0) > 0:
            return "The temperature of the incoming fluid must be above 0 K."
    if geom is not None:
        if float(setup.get("h") or 0) < 0:
            return "The element size cannot be negative."
        h_near, h_far = sizes_mm(geom, setup)
        n = estimate_nodes(geom, setup)
        if n > cf.MAX_NODES // 4:
            return f"The mesh would have about {n:,} nodes: use larger elements or a smaller domain."
    return None


def notes(setup, geom):
    """[sentence]: what a run is likely to get wrong or slow (not an error)."""
    out = []
    if geom is None or geom.get("bodies"):
        return out
    fl, f = setup["flow"], setup["fluid"]
    L = part_size(geom)
    try:
        re = float(f["rho"]) * float(fl["speed"]) * L * 1e-3 / float(f["mu"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        re = 0.0
    if re > RE_STEADY:
        out.append(f"The Reynolds number is {re:,.0f}. This solver is for laminar, steady flow; past a blunt body the real flow above about {RE_STEADY:.0f} "
                   "sheds vortices or is turbulent, so the result is a steady approximation of it (the solve may also stall). Use a lower speed, a smaller part or a more viscous fluid to test the setup.")
    _a, block = frontal_area(geom, setup)
    if block > BLOCKAGE_WARN:
        out.append(f"The part covers {block * 100:.0f} % of the cross-section of the domain: the walls of the box squeeze the flow. Raise the side margin.")
    try:
        n = estimate_nodes(geom, setup)
        if n > MAX_NODES_WARN:
            out.append(f"About {n:,} nodes: this will take long and a lot of memory. Larger elements on the part or a smaller domain make it faster.")
    except (KeyError, TypeError, ValueError):
        pass
    return out


def resolve(geom, setup):
    """-> what `run` takes; fem.FemError for a face that is gone, a size or a mesh option that cannot be used."""
    why = check_ready(setup, geom)
    if why:
        raise fem.FemError(why)
    h_near, h_far = sizes_mm(geom, setup)
    mo = smesh.resolve(geom, setup, h_near)
    if mo and mo.get("type") == "hexdom":
        raise fem.FemError("3D Fluid Flow works on tetrahedra: choose the Tetrahedra mesh type in the advanced mesh options.")
    opts = {"curv": int((mo or {}).get("curv", 10)), "growth": float((mo or {}).get("growth", 1.3)), "hmin": float((mo or {}).get("hmin", 0.0)),
            "face_sizes": [dict(x) for x in (mo or {}).get("face_sizes", [])]}
    if opts["hmin"] and opts["hmin"] >= h_near:
        raise fem.FemError("The minimum size must be smaller than the element size.")
    lo, hi = domain_box(geom, setup)
    inlet, outlet, slip = box_roles(setup["flow"]["dir"])
    r = {"h_near": h_near, "h_far": h_far, "lo": [float(x) for x in lo], "hi": [float(x) for x in hi], "dir": setup["flow"]["dir"], "inlet": inlet,
         "outlet": outlet, "slip": slip, "fluid": dict(setup["fluid"]), "speed": float(setup["flow"]["speed"]), "heat": bool(setup["flow"].get("heat")),
         "T_in": float(setup["flow"].get("T_in") or 293.15), "opts": opts, "probe": setup.get("probe")}
    for key in KEYS:
        items = []
        for i, c in enumerate(setup.get(key) or []):
            nm = sm.name_of(NAMES[key], i, c)
            it = {k: copy.deepcopy(v) for k, v in c.items() if k != "faces"}
            it["name"] = nm
            it["fids"] = sm._fids(geom, c["faces"], nm)
            items.append(it)
        r[key] = items
    return r


def mesh_key(geom, r):
    """The cache key of an air mesh: the part, the box, the sizes and the options."""
    o = r["opts"]
    fs = ";".join(f"{','.join(str(f) for f in sorted(x['fids']))}={x['h']:.8g}" for x in sorted(o["face_sizes"], key=lambda x: sorted(x["fids"])))
    return ("air:" + hashlib.md5(geom["step"]).hexdigest() + ":" + ",".join(f"{x:.8g}" for x in list(r["lo"]) + list(r["hi"])) +
            f":{r['h_near']:.8g}:{r['h_far']:.8g}:{o['growth']:.6g}:{o['curv']}:{o['hmin']:.8g}:{fs}")


def get_mesh(geom, r, cache, cancel=lambda: False, progress=None):
    """The air mesh (cached): {"nodes", "tets", "patches", "h", "unmatched"} (see cfd3d_mesh.air_domain)."""
    key = mesh_key(geom, r)
    q = cache.get(key) if cache is not None else None
    if q is None:
        o = r["opts"]
        q = cmesh.air_domain(geom, r["lo"], r["hi"], r["h_near"], r["h_far"], o["growth"], cancel, progress, curv=o["curv"], hmin=o["hmin"],
                             face_sizes=o["face_sizes"])
        q["quality"] = quality(q)
        if cache is not None:
            for k in [k for k in cache if isinstance(k, str) and k.startswith("air:")]:
                del cache[k]                                      # one air mesh at a time is enough (each is big)
            cache[key] = q
    return q


def quality(q):
    """The shape of the elements, as the 3D FEA reports it (solid_mesh.quality): the tetrahedra of the air are linear ones."""
    return smesh.quality({"nodes": q["nodes"], "tets": q["tets"], "order": 1})


def spec_of(r, q):
    """The setup for the solver: the patches of the box and the part, the fluid, the temperature conditions."""
    f = r["fluid"]
    direction = np.asarray(DIRS[r["dir"]], float)
    walls = [n for n in q["patches"] if n not in BOX]
    spec = {"lscale": 1e-3, "nu": float(f["mu"]) / float(f["rho"]), "rho": float(f["rho"]), "inlet": {r["inlet"]: direction * r["speed"]}, "outlet": [r["outlet"]],
            "slip": list(r["slip"]), "wall": walls}
    if r["heat"]:
        spec.update({"heat": True, "k": float(f["k"]), "cp": float(f["cp"]), "T_in": r["T_in"], "wall_T": {}, "wall_q": {}})
        for c in r["temps"]:
            for fid in c["fids"]:
                if fid in q["patches"]:
                    spec["wall_T"][fid] = float(c["T"])
        for c in r["fluxes"]:
            for fid in c["fids"]:
                if fid in q["patches"] and fid not in spec["wall_T"]:
                    spec["wall_q"][fid] = float(c["q"])
    return spec


def run(geom, r, cache=None, cancel=lambda: False, progress=lambda t: None):
    """Meshes (cached), solves, and returns the result dict of cfd3d_flow.solve_flow with the mesh, the numbers of the report and the conditions' heat added."""
    q = get_mesh(geom, r, cache, cancel, progress)
    spec = spec_of(r, q)
    res = cf.solve_flow(q, spec, progress=progress, cancel=cancel)
    res["mesh"] = q
    res["run"] = r
    res["spec"] = spec
    res["walls"] = list(spec["wall"])
    res["summary"] = summarise(geom, r, q, res)
    return res


def silhouette_area(nodes_mm, tris, axis, n=500):
    """The area (m2) of the shadow of the surface `tris` (triangles of node numbers) cast along the axis 0..2 - what the flow sees of the part, holes and hollows
    included as they are seen from the front.  Rasterised on a grid of n cells along the longer side (an error of about 0.3 % for n = 500)."""
    tris = np.asarray(tris, np.int64)
    if len(tris) == 0:
        return 0.0
    keep = [i for i in range(3) if i != axis]
    P = np.asarray(nodes_mm, float)[:, keep]
    lo = P[tris.ravel()].min(axis=0)
    span = P[tris.ravel()].max(axis=0) - lo
    step = float(span.max()) / n
    if not step > 0:
        return 0.0
    nx, ny = (int(np.ceil(span[0] / step)) + 1, int(np.ceil(span[1] / step)) + 1)
    mask = np.zeros((nx, ny), bool)
    for t in tris:
        a, b, c = P[t] - lo
        i0, i1 = max(int(np.floor(min(a[0], b[0], c[0]) / step - 0.5)), 0), min(int(np.ceil(max(a[0], b[0], c[0]) / step - 0.5)), nx - 1)
        j0, j1 = max(int(np.floor(min(a[1], b[1], c[1]) / step - 0.5)), 0), min(int(np.ceil(max(a[1], b[1], c[1]) / step - 0.5)), ny - 1)
        if i1 < i0 or j1 < j0:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-300:
            continue
        gx, gy = np.meshgrid((np.arange(i0, i1 + 1) + 0.5) * step, (np.arange(j0, j1 + 1) + 0.5) * step, indexing="ij")
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / det
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / det
        mask[i0:i1 + 1, j0:j1 + 1] |= (l1 >= -1e-12) & (l2 >= -1e-12) & (1.0 - l1 - l2 >= -1e-12)
    return float(mask.sum()) * step * step * 1e-6


def energy_verdict(mismatch):
    """-> ("ok" | "warn" | "bad", text) for the energy mismatch of a result."""
    if mismatch < ENERGY_OK:
        return "ok", "OK"
    if mismatch < ENERGY_COARSE:
        return "warn", "COARSE"
    return "bad", "CHECK"


def result_notes(res):
    """What to tell the person after a solve (a list of sentences): a flow that did not settle, a heat balance that does not close."""
    out = []
    s = res["summary"]
    if res["status"] != "converged":
        out.append("The flow did not settle to a steady state: the real flow is probably not steady at this speed (vortices shed behind the part). What is shown is the "
                   "last step, not a solution.")
    if s["mass"]["mismatch"] >= 0.02:
        out.append(f"The flow that enters is {s['mass']['mismatch'] * 100:.1f} % different from the flow that leaves: use smaller elements, or a bigger box if the part "
                   "blocks much of it.")
    if "energy" in s:
        kind, _t = energy_verdict(s["energy"]["mismatch"])
        if kind != "ok":
            out.append(f"The heat from the walls and the heat carried away by the fluid differ by {s['energy']['mismatch'] * 100:.0f} %: the elements on the part are too long "
                       "for the thin layer of fluid that carries the heat (about the size of the part divided by the square root of the Reynolds number). The method is "
                       "first order: with elements half as long the difference shrinks (roughly by a quarter to a third). Heat and drag are over-estimated on a "
                       "coarse mesh.")
    return out


def summarise(geom, r, q, res):
    """The numbers of the report: the force on the part (total, pressure, viscous), the drag along the flow and the sideways forces, the Reynolds number, the
    drag coefficient, the frontal area, the heat of every condition and the checks (mass, energy)."""
    walls = res["walls"]
    F = cf.wall_force(res, walls)
    d = np.asarray(DIRS[r["dir"]], float)
    f = r["fluid"]
    L = part_size(geom) * 1e-3
    U = r["speed"]
    q_dyn = 0.5 * float(f["rho"]) * U * U
    bd = res["boundary"]
    wn = np.asarray(bd.wall_nodes, np.int64)                   # the nodes on the part's walls: the pressures of the report are the ones on the part
    area_wall = 0.0
    for nm in walls:
        area_wall += float(np.linalg.norm(bd.faces(nm)[1], axis=1).sum())
    wall_tris = [q["patches"][nm] for nm in walls if nm in q["patches"]]
    area_front = silhouette_area(q["nodes"], np.vstack(wall_tris), "xyz".index(r["dir"][1])) if wall_tris else 0.0          # the shadow of the part across the flow
    out = {"Re": float(f["rho"]) * U * L / float(f["mu"]), "length_m": L, "q_dyn": q_dyn, "force": F["total"].tolist(), "force_pressure": F["pressure"].tolist(),
           "force_viscous": F["viscous"].tolist(), "drag": float(F["total"] @ d), "drag_pressure": float(F["pressure"] @ d), "drag_viscous": float(F["viscous"] @ d),
           "side": (F["total"] - (F["total"] @ d) * d).tolist(), "area_front_m2": area_front, "area_wall_m2": area_wall,
           "Cd": float(F["total"] @ d) / max(q_dyn * area_front, 1e-300), "mass": res["mass"], "p_max": float(res["p"][wn].max()), "p_min": float(res["p"][wn].min()),
           "speed_max": float(np.linalg.norm(res["u"], axis=1).max()), "flows": []}
    if "T" in res:
        for key, kind in (("temps", "temperature"), ("fluxes", "flux")):
            for c in r[key]:
                names = [fid for fid in c["fids"] if fid in q["patches"]]
                Q = sum(cf.patch_heat(res, nm) for nm in names) if kind == "temperature" else \
                    sum(float((np.linalg.norm(bd.faces(nm)[1], axis=1)).sum()) * float(c["q"]) for nm in names)
                area = sum(float(np.linalg.norm(bd.faces(nm)[1], axis=1).sum()) for nm in names)
                out["flows"].append({"name": c["name"], "kind": kind, "Q": float(Q), "area_m2": area})
        out["energy"] = res["energy"]
        out["T_min"], out["T_max"] = res["T_range"]
    return out


# ---------------------------------------------------------------------------------------------------------------------------- reading a result
def speed_of(res):
    """The speed |u| (m/s) at every node."""
    return np.linalg.norm(res["u"], axis=1)


def part_surface(res):
    """-> (triangles (nt, 3) of the nodes of the mesh on the part's walls, the part-face id of every triangle (-1 for a surface that is not a face))."""
    tris, ids = [], []
    for nm in res["walls"]:
        t = res["mesh"]["patches"][nm]
        tris.append(t)
        ids.append(np.full(len(t), nm if isinstance(nm, int) else -1, np.int64))
    if not tris:
        return np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.vstack(tris), np.concatenate(ids)
