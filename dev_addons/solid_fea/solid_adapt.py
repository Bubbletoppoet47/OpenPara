"""
solid_adapt.py - h-ADAPTIVE MESHING of the 3D FEA: solve, find where the mesh is too coarse, mesh again finer THERE, solve again, and stop when the number
you chose to watch (the criterion) no longer changes by more than the tolerance.  No window in it.

setup["adapt"] = {
  "on":       bool,
  "crit":     "vm" | "umax" | "energy",   the number that has to settle: the peak von Mises stress, the peak displacement or the strain energy
  "tol":      percent (1.0),              converged when the criterion changed by less than this between two loops
  "loops":    1..20 (5),                  the most refinements: loop 0 is your own mesh, every loop after it refines and solves again
  "cap":      elements (0 = automatic),   the largest mesh you allow.  The loops never go above it: when the next mesh would, it is made with less refinement
                                         so that the last mesh lands just under it.  Automatic: the loops stop by themselves when the result settles, or at
                                         AUTO_UNKNOWNS unknowns, or when the memory of this computer is used up.  (A typed maximum is also stopped by memory.)
  "strength": "gentle" | "normal" | "strong",   how much of the estimated error one loop tries to remove
  "hmin":     mm (0 = automatic),         the smallest element the loops may make (automatic: a tenth of the smallest element size, or the minimum size of
                                         the advanced mesh options when that is set)
}
For single parts and for bonded assemblies of tetrahedra.  Not for hex-dominant meshes (`unsupported`).

HOW A LOOP WORKS
  1. The error of every element is estimated from the solution itself (Zienkiewicz-Zhu): the stress an element computes on its own is compared with the stress
     smoothed over its neighbours (averaged at the nodes, per part); the energy of the difference is the element's error eta_e.  The sum over the mesh, against the
     energy of the solution, is the "estimated error" the result reports.
  2. Every element whose error is above its share of a smaller total error gets a smaller target size, h_new = h * (target / eta_e)^(1 / (p + 3/2)) (p = the order
     of the elements; the error of an element goes with h^(p + 3/2)), but not smaller than 0.4 h in one loop and not below the smallest size.  Elements that need
     less than a 10 % change are left alone, and an element is never made coarser than the earlier loops made it.
  3. The sizes are put at the nodes of the last mesh and graded (growth rate of the mesh options), and gmsh meshes the part again with that as its size map.
  4. The new mesh is solved; the criterion of this loop is compared with that of the one before.
The stress at a point load, at a sharp inside corner or at a fixed edge has no finite value, so a PEAK von Mises there keeps growing with every loop: the loops
then run to the end (the most loops, or the largest mesh) and say so.  Displacement and strain energy do converge there.

HOW BIG A MESH MAY GET
  The solver itself has no size limit that matters here: above fem.DIRECT_LIMIT unknowns it uses multigrid (see solid_fem).  What stops the loops is the
  maximum you typed ("max"), the automatic limit when you typed none ("auto"), and the memory that is free on this computer ("memory"; fem.memory_ceiling).
  When the next mesh would cross the limit, the refinement is damped (the size reduction of every element raised to a power t < 1, t found from the predicted
  element count and one or two trial meshes) so that the last mesh is the largest that fits, just under the limit.

    default_adapt() / complete(a) / options(setup) / validate(a) / unsupported(geom, setup) / resolve(geom, setup)
    indicator(q, r, u)         -> the error of every element (see above)
    plan(geom, r, h, mesh)     -> [(stage, size)] for the progress bar
    run(geom, r, h, cache, cancel, progress, get_mesh, solve_mesh)   -> the result of the last loop with result["adapt"] = what the loops did
"""
import copy
import math
import time

import numpy as np
import scipy.spatial as sps

import solid_elem as elem
import solid_fem as fem
import solid_mesh as smesh

CRITERIA = {"vm": ("Von Mises stress (peak)", "MPa"), "umax": ("Displacement (peak)", "mm"), "energy": ("Strain energy", "N mm")}
STRENGTHS = {"gentle": ("Gentle", 0.7), "normal": ("Normal", 0.5), "strong": ("Aggressive", 0.35)}
DEFAULTS = {"on": False, "crit": "vm", "tol": 1.0, "loops": 5, "cap": 0, "strength": "normal", "hmin": 0.0}
LOOPS_RANGE = (1, 20)
TOL_RANGE = (0.001, 50.0)
FMIN = 0.4                  # the most one loop makes an element smaller (a size factor)
FSKIP = 0.9                 # an element that would get less than a 10 % smaller size is left alone
AUTO_FLOOR = 10.0           # the automatic smallest size: the smallest element size over this
AUTO_UNKNOWNS = 400000      # the automatic largest mesh (unknowns), when no maximum is typed: about two minutes a solve on a modest computer, 2 GB of memory
LAND = 0.95                 # the mesh that has to fit under the limit is aimed at this share of it
LAND_MIN = 1.2              # a loop that could add less than this factor of elements is not worth its solve: the loops stop at the limit instead
LAND_TRIES = 2              # extra trial meshes to land under the limit
LAND_LOW = 0.85             # a mesh that lands under this share of the limit gets one more try
GROWTH_PER_LOOP = 2.2       # the number of elements a loop is expected to make (only for the progress bar's estimate)
BIG = 1e30


def default_adapt():
    return copy.deepcopy(DEFAULTS)


def complete(a):
    """A stored dict (maybe from an older file, or missing) with every key present."""
    d = default_adapt()
    d.update({k: v for k, v in (a or {}).items() if k in DEFAULTS})
    return d


def options(setup):
    return complete(setup.get("adapt"))


def validate(a):
    """The reason why the settings cannot be used, or None."""
    a = complete(a)
    if a["crit"] not in CRITERIA:
        return "The criterion must be the von Mises stress, the displacement or the strain energy."
    try:
        tol, loops, cap, hmin = float(a["tol"]), int(a["loops"]), float(a["cap"]), float(a["hmin"])
    except (TypeError, ValueError):
        return "The adaptive mesh settings must be numbers."
    if not TOL_RANGE[0] <= tol <= TOL_RANGE[1]:
        return f"The convergence tolerance must be between {TOL_RANGE[0]:g} % and {TOL_RANGE[1]:g} %."
    if not LOOPS_RANGE[0] <= loops <= LOOPS_RANGE[1]:
        return f"The maximum number of loops must be {LOOPS_RANGE[0]} to {LOOPS_RANGE[1]}."
    if cap < 0 or (0 < cap < 100):
        return "The largest number of elements must be at least 100 (or 0 for automatic)."
    if hmin < 0:
        return "The smallest element size must be positive (or blank for automatic)."
    if a["strength"] not in STRENGTHS:
        return "The refinement must be gentle, normal or aggressive."
    return None


def unsupported(geom, setup):
    """Why adaptive meshing cannot be used on this setup, or None."""
    if smesh.options(setup)["type"] != "tets":
        return "Adaptive meshing works with tetrahedra only: choose the tetrahedra mesh type (or switch the adaptive mesh off)."
    return None


def resolve(geom, setup):
    """None when the adaptive mesh is off, else the checked settings; a fem.FemError says what cannot be used."""
    a = options(setup)
    if not a["on"]:
        return None
    why = validate(a) or unsupported(geom, setup)
    if why:
        raise fem.FemError(why)
    return {"crit": a["crit"], "tol": float(a["tol"]), "loops": int(a["loops"]), "cap": int(a["cap"]), "reduce": STRENGTHS[a["strength"]][1],
            "strength": a["strength"], "hmin": float(a["hmin"])}


# ------------------------------------------------------------------------------------------------------------------------ the error of the elements
def _D(r, body):
    mats = r.get("materials")
    m = mats[body] if mats else r["material"]
    return fem.material_matrix(m["E"], m["nu"])


def indicator(q, r, u):
    """The error of every element of the mesh `q` (tetrahedra: the groups in order, as fem.stresses has them) whose solution is `u` ((nn, 3), mm):
    {"eta2": the squared energy of (smoothed - computed stress) per element (N mm), "en2": the energy of the computed stress (twice the strain energy,
     per element), "vol", "body", "eta": sqrt of all of it, "norm": the energy norm squared of the solution, "theta": the estimated error of the whole mesh
     (a fraction: eta / sqrt(norm + eta^2))}."""
    nodes = np.asarray(q["nodes"], float)
    groups = q["groups"]
    if any(g["kind"] != "tet" for g in groups):
        raise fem.FemError("The error of a mesh can be estimated for tetrahedra only.")
    nc = int(max(int(g["conn"][:, :4].max()) for g in groups)) + 1            # the corner nodes come first, the mid-edge nodes after them
    nb = 1 + max(int(g.get("body", 0)) for g in groups)
    uf = np.asarray(u, float).reshape(-1)
    parts = []
    for g in groups:
        body = int(g.get("body", 0))
        conn = g["conn"]
        D = _D(r, body)
        Ci = np.linalg.inv(D)
        dN, gw, _ns = fem._rule(conn.shape[1])
        corners = [fem._dNdL(c) for c in np.eye(4)] if conn.shape[1] == 10 else None      # the stress at the four corners: a quadratic element has a linear one
        sig, cor, vol = [], [], []
        for s in range(0, len(conn), 8000):
            e = min(s + 8000, len(conn))
            gL, V = fem._grad_L(nodes, conn, s, e)
            ue = uf[fem._edofs(conn[s:e])]
            at = lambda pts: np.stack([np.einsum("eri,ei->er", elem.bmat(np.einsum("ik,ekx->eix", d, gL)), ue) @ D.T for d in pts], axis=1)
            sig.append(at(dN))                                                  # (ne, points, 6)
            cor.append(at(corners) if corners is not None else np.repeat(sig[-1], 4, axis=1))         # a linear tetrahedron: its one stress at all four
            vol.append(V)
        parts.append({"conn": conn, "body": body, "Ci": Ci, "w": np.asarray(gw, float), "sig": np.concatenate(sig), "vol": np.concatenate(vol),
                      "cor": np.concatenate(cor)})
    acc = np.zeros((nb * nc, 6))
    wsum = np.zeros(nb * nc)
    for p in parts:                                                            # the stress at the corner nodes: the volume weighted mean of the elements around
        key = p["body"] * nc + p["conn"][:, :4]
        for j in range(4):
            for c in range(6):
                acc[:, c] += np.bincount(key[:, j], weights=p["vol"] * p["cor"][:, j, c], minlength=nb * nc)
            wsum += np.bincount(key[:, j], weights=p["vol"], minlength=nb * nc)
    smooth = acc / np.maximum(wsum, 1e-300)[:, None]
    eta2, en2, vols, body = [], [], [], []
    for p in parts:
        key = p["body"] * nc + p["conn"][:, :4]
        S = smooth[key]                                                         # (ne, 4, 6)
        e2 = np.zeros(len(key))
        h2 = np.zeros(len(key))
        for gi, L in enumerate(fem.GAUSS):
            ss = np.einsum("i,eic->ec", L, S)
            sh = p["sig"][:, min(gi, p["sig"].shape[1] - 1)]                    # a linear tetrahedron has one (constant) stress
            df = ss - sh
            e2 += fem.GW[gi] * np.einsum("ec,cd,ed->e", df, p["Ci"], df)
            h2 += fem.GW[gi] * np.einsum("ec,cd,ed->e", sh, p["Ci"], sh)
        eta2.append(e2 * p["vol"])
        en2.append(h2 * p["vol"])
        vols.append(p["vol"])
        body.append(np.full(len(key), p["body"], np.int64))
    eta2, en2 = np.concatenate(eta2), np.concatenate(en2)
    eta, norm = math.sqrt(float(eta2.sum())), float(en2.sum())
    return {"eta2": eta2, "en2": en2, "vol": np.concatenate(vols), "body": np.concatenate(body), "eta": eta, "norm": norm,
            "theta": eta / math.sqrt(max(norm + eta * eta, 1e-300))}


def element_error_percent(ind):
    """The error of every element against the energy of its own solution, in percent (what the 'Estimated error' colours show)."""
    return 100.0 * np.sqrt(ind["eta2"] / np.maximum(ind["en2"] + ind["eta2"], 1e-300))


def node_error(q, ind):
    """The element errors (percent) as a value at every node of the mesh: the volume weighted mean of the elements around the node."""
    nn = len(q["nodes"])
    val = element_error_percent(ind)
    acc, w = np.zeros(nn), np.zeros(nn)
    base = 0
    for g in q["groups"]:
        gc = g["conn"]
        sl = slice(base, base + len(gc))
        for j in range(gc.shape[1]):
            acc += np.bincount(gc[:, j], weights=(val * ind["vol"])[sl], minlength=nn)
            w += np.bincount(gc[:, j], weights=ind["vol"][sl], minlength=nn)
        base += len(gc)
    return acc / np.maximum(w, 1e-300)


# ------------------------------------------------------------------------------------------------------------------------ the size map of the next mesh
def _edges(tets):
    pairs = np.concatenate([tets[:, [a, b]] for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))])
    pairs = np.sort(pairs, axis=1)
    n = int(pairs.max()) + 1
    k = np.unique(pairs[:, 0].astype(np.int64) * n + pairs[:, 1])
    return np.stack([k // n, k % n], axis=1)


def _mean_edge(xyz, tets):
    c = xyz[tets]
    L = [np.linalg.norm(c[:, a] - c[:, b], axis=1) for a, b in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))]
    return np.mean(L, axis=0)


def grade(xyz, edges, S, growth, iters=60):
    """Limits the change of the size map along every edge of the mesh: S[a] <= S[b] + (growth - 1) * |ab|."""
    S = S.copy()
    a, b = edges[:, 0], edges[:, 1]
    lim = (growth - 1.0) * np.linalg.norm(xyz[a] - xyz[b], axis=1)
    for _ in range(iters):
        before = S.copy()
        np.minimum.at(S, a, before[b] + lim)
        np.minimum.at(S, b, before[a] + lim)
        if np.array_equal(S, before):
            break
    return S


def _prepare(q, ind, order, reduce, field):
    """What the size map needs from the mesh and its error, and does not change with the damping: the corner nodes, the tetrahedra, the size every element has
    (or an earlier loop already gave its nodes), and the factor each wants (1 = leave it, FMIN = as much finer as one loop may make it)."""
    nc = int(q["conn"][:, :4].max()) + 1
    xyz = np.asarray(q["nodes"], float)[:nc]
    tets = np.asarray(q["conn"][:, :4], np.int64)
    ne = len(tets)
    meas = _mean_edge(xyz, tets)
    held = np.full(nc, BIG)
    if field is not None:                                                       # the earlier size at these nodes (the nearest node of the earlier mesh)
        _d, idx = sps.cKDTree(field["xyz"]).query(xyz)
        held = field["S"][idx].copy()
    base = np.minimum(meas, held[tets].min(axis=1))
    eta = np.sqrt(np.maximum(ind["eta2"], 0.0))
    target = reduce * ind["eta"] / math.sqrt(ne)
    expo = 1.0 / (order + 1.5)
    fac = np.clip((target / np.maximum(eta, 1e-300)) ** expo, FMIN, 1.0)
    return {"xyz": xyz, "tets": tets, "ne": ne, "held": held, "base": base, "fac": fac}


def _refined(P, floor, damp):
    """(the factor of every element with the damping, which elements are marked, which of them can be refined, their new sizes)."""
    fac = P["fac"] ** damp if damp != 1.0 else P["fac"]
    marked = fac < FSKIP
    can = marked & (P["base"] * FSKIP > floor)                                 # an element that is already at the smallest size cannot be refined
    new = np.maximum(fac * P["base"], floor)
    return marked, can, new


def predicted_elements(P, floor, damp=1.0):
    """The number of elements the next mesh will have, about: every element that is refined becomes (old size / new size)^3 elements."""
    _marked, can, new = _refined(P, floor, damp)
    return float(np.where(can, (P["base"] / new) ** 3, 1.0).sum())


def fit_damp(P, floor, want, kappa=1.0):
    """The damping t (1 = the refinement the error asks for, near 0 = hardly any) at which kappa * predicted_elements is `want`; None when even the least
    refinement is above it.  kappa = what a real mesh had (its elements over the prediction), so that the prediction is corrected by what has been seen."""
    lo, hi = 0.02, 1.0
    if kappa * predicted_elements(P, floor, lo) > want:
        return None
    if kappa * predicted_elements(P, floor, hi) <= want:
        return hi
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        if kappa * predicted_elements(P, floor, mid) <= want:
            lo = mid
        else:
            hi = mid
    return lo


def size_map(q, ind, order, reduce, floor, field, growth, hbig, damp=1.0, prep=None):
    """The size map of the next mesh from the error `ind` of the mesh `q`.  `field` = the map of the loop before ({"xyz", "S"} or None): what an earlier
    loop made finer stays finer.  `damp` < 1 refines less (see fit_damp); `prep` = _prepare(...) when the caller has it already.
    -> ({"xyz", "tets", "size"} for gmsh, the field to keep for the next loop, a dict of counts)."""
    P = prep or _prepare(q, ind, order, reduce, field)
    xyz, tets, ne = P["xyz"], P["tets"], P["ne"]
    marked, can, new = _refined(P, floor, damp)
    S = P["held"].copy()
    for j in range(4):
        np.minimum.at(S, tets[:, j], np.where(can, new, BIG))
    S = grade(xyz, _edges(tets), S, growth)
    keep = {"xyz": xyz, "S": S}
    out = {"xyz": xyz, "tets": tets, "size": np.minimum(S, hbig)}
    info = {"marked": int(marked.sum()), "refined": int(can.sum()), "at_floor": int((marked & ~can).sum()), "elements": int(ne),
            "predicted": float(np.where(can, (P["base"] / new) ** 3, 1.0).sum()), "damp": float(damp)}
    return out, keep, info


# ------------------------------------------------------------------------------------------------------------------------ the loop
class _Loop:
    """The progress function of the solver with the loop in front of every message (the stage and part calls go straight to the tracker)."""

    def __init__(self, inner, text):
        self.inner, self.text = inner, text

    def __call__(self, t):
        self.inner(f"{self.text}: {t}")

    def __getattr__(self, name):
        if name in ("stage", "part"):
            return getattr(self.inner, name)
        raise AttributeError(name)


def plan(geom, r, h, mesh=None):
    """[(stage, size)] of the whole run, at its longest (every loop is made): the progress bar's estimate.  `mesh` = the starting mesh when it exists."""
    import solid_progress as spg
    a = r["adapt"]
    el0 = float(len(mesh["conn"])) if mesh is not None else spg.estimate_for(geom, h, (r.get("mesh") or {}).get("body_h"))
    quad = (r.get("mesh") or {}).get("order", 2) == 2
    per_el = spg.NODES_PER_ELEMENT if quad else 0.22
    bb = (geom or {}).get("bbox")
    try:
        ext = [abs(float(bb[1][i]) - float(bb[0][i])) for i in range(3)] if bb else None
    except (TypeError, ValueError, IndexError):
        ext = None
    out = [] if mesh is not None else [("mesh", el0)]
    elmax, _kind = element_limit(a, *unknown_limit(a), per_el)
    for k in range(a["loops"] + 1):
        el = min(el0 * GROWTH_PER_LOOP ** k, max(elmax, el0))
        nodes = el * per_el
        if k:
            out.append(("mesh", el))
        out.append(("assemble", el))
        out.append(("factor", spg.factor_cost(3.0 * nodes, ext)) if 3.0 * nodes <= spg.DIRECT_LIMIT else ("cg", 3.0 * nodes))
        out.append(("stress", 2.0 * el))                                       # the stresses, and the error estimate that costs about the same
    return out


def _peak_edge(q, res):
    """The size (mean edge, mm) of the element with the largest von Mises stress."""
    i = int(np.argmax(res["vm_el"]))
    return float(_mean_edge(np.asarray(q["nodes"], float), np.asarray(q["conn"][i, :4], np.int64)[None, :])[0])


def criterion_value(res, crit):
    return float({"vm": res["vm_max"], "umax": res["umax"], "energy": res["energy"]}[crit])


def unknown_limit(a, free=None):
    """(the most unknowns a mesh may have, what sets it): the free memory ("memory"), and when no largest mesh is typed the automatic limit ("auto").
    (None, None) when nothing limits it.  A typed maximum is not an unknown limit: it counts elements (see element_limit)."""
    mem = fem.memory_ceiling(free)
    auto = None if a["cap"] else AUTO_UNKNOWNS
    if mem is not None and (auto is None or mem <= auto):
        return mem, "memory"
    return auto, ("auto" if auto is not None else None)


def element_limit(a, ulimit, ukind, ratio):
    """(the most elements the next mesh may have, what sets it): the typed maximum ("max") or the unknown limit (`ulimit`, kind `ukind`) turned into elements
    with `ratio` = the nodes per element of the mesh at hand.  (inf, None) when nothing limits it."""
    lim, kind = math.inf, None
    if a["cap"]:
        lim, kind = float(a["cap"]), "max"
    if ulimit is not None and ulimit / (3.0 * max(ratio, 1e-9)) < lim:
        lim, kind = ulimit / (3.0 * max(ratio, 1e-9)), ukind
    return lim, kind


def limit_reason(kind, a, n, ulimit):
    """The plain words for a loop that stopped at a limit; n = the elements of the last mesh."""
    if kind == "max":
        return f"Reached your maximum of {int(a['cap']):,} elements (the last mesh has {n:,})."
    if kind == "memory":
        free = fem.available_memory()
        return (f"Stopped at {n:,} elements: a finer mesh would need more memory than this computer has free" +
                (f" (about {free / 1e9:.1f} GB)." if free else "."))
    return f"Reached the automatic size limit of about {int(ulimit):,} unknowns ({n:,} elements). Type a larger 'Largest mesh' to go further."


OUTCOME_TEXT = {"converged": "converged", "max": "reached maximum", "auto": "reached size limit", "memory": "stopped by memory", "not converged": "not converged"}


def outcome(ad):
    """How the loops ended, in one word: converged | max | auto | memory | not converged (a key of OUTCOME_TEXT)."""
    if ad["converged"]:
        return "converged"
    return ad.get("limit") or "not converged"


def _mesh(geom, h, opts, cancel, progress):
    raw = fem.mesh_solid(geom, h, cancel, progress, opts)
    q = fem.linear(raw) if opts["order"] == 1 else fem.quadratic(raw)
    q["quality"] = smesh.quality(q)
    return q


def run(geom, r, h, cache, cancel, progress, get_mesh, solve_mesh):
    """Solves, refines and solves again (see the top of the file).  `get_mesh(geom, h, cache, cancel, progress, opts)` makes (or takes from the cache) the
    starting mesh and `solve_mesh(geom, r, h, q, cancel, progress)` solves one mesh; both are solid_model's.  -> the result of the last mesh that was solved,
    with result["adapt"] = {crit, tol, loops_max, loops (refinements made), converged, reason, change (percent), err (estimated error, percent), history: [...]}"""
    a = r["adapt"]
    base = r.get("mesh") or {"type": "tets", "order": 2, "hmin": 0.0, "growth": 1.3, "curv": 10, "face_sizes": [], "body_h": {}}
    order = int(base["order"])
    sizes = fem.element_sizes(geom, h, base)
    hbig, hlow = max(sizes), min(sizes)
    floor = a["hmin"] or float(base.get("hmin") or 0.0) or hlow / AUTO_FLOOR
    q = get_mesh(geom, h, cache, cancel, progress, r.get("mesh"))
    try:
        progress.expect(plan(geom, r, h, q), cyclic=True)                      # the whole run as the bar's plan (a tracker only; a plain function has no plan)
    except (AttributeError, TypeError):
        pass
    maxloops = a["loops"]
    ulim, ukind = unknown_limit(a)
    per_el0 = len(q["nodes"]) / max(len(q["conn"]), 1)
    warning = None
    if a["cap"]:                                                                # a typed maximum that this computer cannot hold: said at the start
        free = fem.available_memory()
        need = fem.memory_estimate(3.0 * a["cap"] * per_el0)
        if free and need > fem.MEM_SHARE * free:
            warning = (f"Your maximum of {int(a['cap']):,} elements would need about {need / 1e9:.1f} GB to solve and this computer has about {free / 1e9:.1f} GB "
                       "free: the loops stop earlier, when the memory is used up.")
            progress(warning)
    hist, field, prev = [], None, None
    reason, converged, res, ind, qlast, refined, last, pe_prev = None, False, None, None, q, None, None, None
    limit, held = None, None                                                    # what limit ended the loops; the limit that held the last mesh's refinement back
    nm = {"vm": "von Mises stress (peak)", "umax": "displacement (peak)", "energy": "strain energy"}[a["crit"]]
    for k in range(maxloops + 1):
        if cancel():
            raise fem.Cancelled()
        t0 = time.time()
        lp = _Loop(progress, f"Loop {k} of {maxloops}")
        res = solve_mesh(geom, r, h, q, cancel, lp)
        fem._stage(progress, "stress", float(len(res["conn"])))
        ind = indicator(q, r, res["u"])
        qlast = q
        val = criterion_value(res, a["crit"])
        change = None if prev is None else abs(val - prev) / max(abs(val), 1e-300) * 100.0
        pe = _peak_edge(q, res) if a["crit"] == "vm" else None
        n_now = int(len(res["conn"]))
        hist.append({"loop": k, "elements": n_now, "nodes": int(len(res["nodes"])), "unknowns": int(res["info"]["unknowns"]), "value": val,
                     "change": change, "err": 100.0 * float(ind["theta"]), "refined": refined, "seconds": time.time() - t0})
        if change is not None and change <= a["tol"]:
            if held is not None:                                                # this mesh was refined less than the error asked for: a small change shows nothing
                limit = held
                reason = (limit_reason(held, a, n_now, ulim) + f" The {nm} changed by {change:.3g} % in the last loop, but that loop was held back by the "
                          "limit, so the change does not show that the result has settled.")
            elif last is not None and last["marked"] and last["at_floor"] > 0.5 * last["marked"]:           # most of what needed refining could not be refined
                reason = (f"The {nm} changed by {change:.3g} %, but the smallest element size ({floor:.3g} mm) limits the refinement: {last['at_floor']:,} of the "
                          f"{last['marked']:,} elements that need refining are already that small, so the small change does not show that the result has settled "
                          f"(estimated error {100.0 * float(ind['theta']):.3g} %). Allow a smaller size or a larger mesh.")
            elif pe is not None and pe_prev is not None and pe <= 1.3 * floor and pe > 0.8 * pe_prev:          # the peak is in elements that could not get smaller
                reason = (f"The peak von Mises stress changed by {change:.3g} % but it lies in elements at the smallest size ({floor:.3g} mm) that the last loop could "
                          "not make smaller, so the loops cannot tell whether it has settled. It may keep growing with smaller elements (a point load, a sharp "
                          "inside corner or a fixed edge has no finite stress): allow a smaller size, or watch the displacement or the strain energy.")
            else:
                converged, reason = True, f"The {nm} changed by {change:.3g} % in the last loop (tolerance {a['tol']:g} %)."
            break
        if k == maxloops:
            reason = f"The most loops ({maxloops}) are done and the {nm} still changed by {change:.3g} %." if change is not None else "No loops."
            if held is not None:
                limit = held
                reason = limit_reason(held, a, n_now, ulim) + " " + reason
            break
        elim, ekind = element_limit(a, ulim, ukind, len(res["nodes"]) / max(n_now, 1))
        if n_now >= elim or elim < LAND_MIN * n_now:                            # at the limit, or so close to it that a loop could hardly add anything
            limit, reason = ekind, limit_reason(ekind, a, n_now, ulim)
            break
        P = _prepare(q, ind, order, a["reduce"], field)
        sm_, field_next, info = size_map(q, ind, order, a["reduce"], floor, field, float(base.get("growth") or 1.3), hbig, prep=P)
        if info["refined"] == 0:
            reason = ("Nothing can be refined any more: the elements that need it are at the smallest size." if info["marked"] else
                      "No element needs refining: the estimated error is the same everywhere.")
            break
        opts = dict(base, hmin=floor, size_map=sm_, expect=float(n_now) * GROWTH_PER_LOOP)
        if cancel():
            raise fem.Cancelled()
        progress(f"Loop {k + 1} of {maxloops}: meshing ({info['refined']:,} of {info['elements']:,} elements refined)")
        qn = _mesh(geom, h, opts, cancel, progress)
        ratio_n = len(qn["nodes"]) / max(len(qn["conn"]), 1)
        elim, ekind = element_limit(a, ulim, ukind, ratio_n)
        cand = (qn, field_next, info)                                           # the mesh the error asks for
        fits = []                                                               # the meshes that are under the limit
        tries = 0
        while True:
            n = len(cand[0]["conn"])
            if n <= elim:
                fits.append(cand)
            low = cand[2]["damp"] < 1.0 and n < LAND_LOW * elim                 # landed well under: one more try, with what this mesh has shown
            if (n <= elim and not low) or tries >= LAND_TRIES:
                break
            kappa = n / max(cand[2]["predicted"], 1.0)
            t = fit_damp(P, floor, LAND * elim, kappa)
            if t is None or t >= 1.0 or abs(t - cand[2]["damp"]) < 0.01:
                break
            progress(f"Loop {k + 1} of {maxloops}: the next mesh would have {n:,} elements, the limit is {int(elim):,}: " + ("refining less" if n > elim else "refining a little more"))
            sm_, field_n2, info2 = size_map(q, ind, order, a["reduce"], floor, field, float(base.get("growth") or 1.3), hbig, damp=t, prep=P)
            if info2["refined"] == 0:
                break
            cand = (_mesh(geom, h, dict(base, hmin=floor, size_map=sm_, expect=info2["predicted"]), cancel, progress), field_n2, info2)
            tries += 1
        if not fits:                                                            # could not be brought under the limit: the last mesh that was solved is the answer
            limit, reason = ekind, limit_reason(ekind, a, n_now, ulim)
            break
        qn, field_next, info = max(fits, key=lambda c: len(c[0]["conn"]))
        held_now = ekind if info["damp"] < 1.0 else None
        held = held_now
        field, prev, q, refined, last, pe_prev = field_next, val, qn, info["refined"], info, pe
    res["node_err"] = node_error(qlast, ind)
    res["adapt"] = {"crit": a["crit"], "tol": a["tol"], "loops_max": maxloops, "loops": len(hist) - 1, "converged": bool(converged), "reason": reason,
                    "change": hist[-1]["change"], "err": hist[-1]["err"], "history": hist, "floor": float(floor), "strength": a["strength"],
                    "limit": limit, "warning": warning, "max_elements": int(a["cap"])}
    return res


def cap_hit(a, n_elements):
    return bool(a["cap"]) and n_elements >= a["cap"]
