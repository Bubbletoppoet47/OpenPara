"""thermal3d_model.py - the SETUP of a 3D Thermal analysis (what the panel edits) and the run that turns it into a result.  No window in it.

The geometry and the mesh are the 3D FEA's (solid_base / solid_model: the part or the assembly, the faces and their patches, the element sizes); this adds the
heat-transfer physics.  Everything stored is SI and ABSOLUTE temperature (kelvin): the heat units of File > Units only change what is shown and typed.

setup = {
  ... the keys of solid_base.SolidBase.new_setup(): "dims", "splits", "bond_tol", "body_mats", "body_h", "h", "mesh" ...,
  "material": {"name", "k": W/(m K), "rho": kg/m3, "cp": J/(kg K), "gen": W/m3},          the part's material (and the one an assembly's bodies fall back on)
  "body_mats": {body name: {"name", "k", "rho", "cp", "gen"}}       an ASSEMBLY: the material of the bodies that were changed from the one found for their name
  "temps":  [{"name", "faces": [face signature], "T": K}]                       fixed temperature
  "fluxes": [{"name", "faces", "q": W/m2}]                                       heat flux INTO the body
  "powers": [{"name", "faces", "P": W}]                                          heat flow INTO the body, spread over the area of the faces
  "convs":  [{"name", "faces", "h": W/(m2 K), "Tinf": K}]                        convection to a fluid
  "rads":   [{"name", "faces", "eps", "Ts": K}]                                  radiation to surroundings (not between the faces of the model)
  "ins":    [{"name", "faces"}]                                                  insulated (nothing is added; it makes the choice visible and checked)
  "analysis": "steady" | "transient", "T0": K, "t_end": s, "steps": n, "theta": 1 (backward Euler) | 0.5 (Crank-Nicolson), "frames": pictures kept
  "probe": [x, y, z] or None
}
Faces are signatures as in the 3D FEA (see solid_geom.face_sig): a whole face, or a patch of a split face.  `resolve(geom, setup)` turns them into face ids of
the (rebuilt) part - a lost face is an error naming the condition; the result is what thermal3d_fem.solve takes (plus "h" and "mesh").
"""
import copy

import numpy as np

import solid_fem as fem
import solid_model as sm
import solid_mesh as smesh
import thermal3d_fem as tf

CONDITION_KINDS = (("Fixed temperature", "temps"), ("Heat flux", "fluxes"), ("Heat flow", "powers"), ("Convection", "convs"), ("Radiation", "rads"),
                   ("Insulated", "ins"))
KEYS = tuple(k for _n, k in CONDITION_KINDS)
KIND_OF = {"temps": "temp", "fluxes": "flux", "powers": "power", "convs": "conv", "rads": "rad", "ins": "ins"}
VALUES = {"temps": ("T",), "fluxes": ("q",), "powers": ("P",), "convs": ("h", "Tinf"), "rads": ("eps", "Ts"), "ins": ()}
NAMES = dict((k, n) for n, k in CONDITION_KINDS)
ANALYSES = {"steady": "Steady state", "transient": "Transient (changing with time)"}
K0 = 273.15


def default_material():
    import thermal_mat
    m = thermal_mat.find(thermal_mat.DEFAULT) or thermal_mat.builtin()[0]
    return {"name": m["name"], "k": m["k"], "rho": m["rho"], "cp": m["cp"], "gen": 0.0}


def default_setup():
    s = {"dims": {}, "splits": [], "bond_tol": 0.0, "body_mats": {}, "body_h": {}, "h": 0.0, "mesh": smesh.default_mesh(), "material": default_material()}
    for k in KEYS:
        s[k] = []
    s.update({"analysis": "steady", "T0": 293.15, "t_end": 600.0, "steps": 60, "theta": 1.0, "frames": 40, "probe": None})
    return s


def body_materials(geom, setup):
    """[material dict per body of an assembly]: the one chosen for it in the setup, else the one the library has for the name of the body's material (the
    part's own density when it has one), else the material of the tab."""
    import thermal_mat
    base = setup["material"]
    mine = setup.get("body_mats") or {}
    out = []
    for b in geom["bodies"]:
        bm = b.get("material") or {}
        found = thermal_mat.for_part_material({"name": bm.get("name"), "density": bm.get("rho")})
        m = dict(found) if found else {"name": bm.get("name") or base.get("name") or "", "k": base["k"], "rho": base["rho"], "cp": base["cp"]}
        m["gen"] = 0.0
        m.update({k: v for k, v in (mine.get(b["name"]) or {}).items() if v is not None})
        out.append(m)
    return out


def material_problem(m, who=""):
    """The reason why a thermal material cannot be used, or None."""
    pre = f"{who}: " if who else ""
    try:
        if not float(m["k"]) > 0:
            return f"{pre}the thermal conductivity must be greater than zero."
        if not (float(m["rho"]) > 0 and float(m["cp"]) > 0):
            return f"{pre}the density and the specific heat must be greater than zero."
        float(m.get("gen") or 0.0)
    except (KeyError, TypeError, ValueError):
        return f"{pre}the material needs a conductivity, a density and a specific heat."
    return None


def check_ready(setup, geom=None):
    """The reason why nothing can run yet, or None."""
    mats = body_materials(geom, setup) if geom is not None and geom.get("bodies") else [setup["material"]]
    bodies = [b["name"] for b in geom["bodies"]] if geom is not None and geom.get("bodies") else [""]
    for m, who in zip(mats, bodies):
        why = material_problem(m, who)
        if why:
            return why[0].upper() + why[1:]
    if setup.get("analysis", "steady") == "transient":
        if not float(setup.get("T0") or 0) > 0:
            return "The starting temperature must be above 0 K."
        if not float(setup.get("t_end") or 0) > 0:
            return "The end time must be greater than zero."
        if int(setup.get("steps") or 0) < 1:
            return "A transient run needs at least one time step."
        return None
    holds = bool(setup.get("temps")) or any(float(c.get("h") or 0) > 0 for c in setup.get("convs") or []) or \
        any(float(c.get("eps") or 0) > 0 for c in setup.get("rads") or [])
    if not holds:
        return ("Add a fixed temperature, convection or radiation: without one the temperature of a steady-state problem is not defined. "
                "(A transient analysis does not need one.)")
    return None


def resolve(geom, setup):
    """-> what thermal3d_fem.solve takes, plus "h" and "mesh"; fem.FemError for a face that is gone, a mesh type that cannot be used or a number that is wrong."""
    h = float(setup.get("h") or 0.0)
    r = {"h": h, "mesh": smesh.resolve(geom, setup, h or sm.auto_h(geom)), "probe": setup.get("probe")}
    if r["mesh"] and r["mesh"].get("type") == "hexdom":
        raise fem.FemError("3D Thermal works on tetrahedra: choose the Tetrahedra mesh type in the advanced mesh options.")
    if geom.get("bodies"):
        r["materials"] = body_materials(geom, setup)
    else:
        r["materials"] = [dict(setup["material"])]
    names = [b["name"] for b in geom["bodies"]] if geom.get("bodies") else [""]
    for m, who in zip(r["materials"], names):
        why = material_problem(m, who)
        if why:
            raise fem.FemError(why[0].upper() + why[1:])
    for key in KEYS:
        items = []
        for i, c in enumerate(setup.get(key) or []):
            nm = sm.name_of(NAMES[key], i, c)
            it = {k: copy.deepcopy(v) for k, v in c.items() if k != "faces"}
            it["name"] = nm
            it["fids"] = sm._fids(geom, c["faces"], nm)
            items.append(it)
        r[key] = items
    for k in ("analysis", "T0", "t_end", "steps", "theta", "frames"):
        if k in setup:
            r[k] = setup[k]
    return r


def spec_of(r):
    """The setup for the solver: the resolved one in metres per mesh unit (the mesh of the 3D FEA is in mm)."""
    s = dict(r)
    s["lscale"] = 1e-3
    return s


def run(geom, r, cache=None, cancel=lambda: False, progress=lambda t: None):
    """Meshes (cached), solves and returns the result dict of thermal3d_fem.solve, with the mesh it was solved on (res["q"] is the heat flux; res["mesh"] the mesh)."""
    h = r["h"] or sm.auto_h(geom)
    q = sm.get_mesh(geom, h, cache, cancel, progress, r.get("mesh"))
    res = tf.solve(q, spec_of(r), progress=progress, cancel=cancel)
    res["mesh"] = q
    res["h_used"] = h
    res["names"] = {k: [c["name"] for c in r[k]] for k in KEYS}
    return res
