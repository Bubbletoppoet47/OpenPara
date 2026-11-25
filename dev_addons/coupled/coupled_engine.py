"""coupled_engine.py - Coupled Physics without a window: how a field is handed from one analysis to another, and the loop that runs the analyses in order.

Every analysis keeps its OWN mesh (a heat problem wants a fine mesh near a hot spot, a stress problem near a corner), so a field that one computes at its nodes must
be worked out at the nodes of the other.  `Locator` finds, for any point, the triangle (2D) or tetrahedron (3D) of the first mesh that holds it, and the field is
interpolated linearly there: a field that is linear in space is handed over exactly, and no value outside the range of the source can appear (the barycentric weights
are never negative).  A point that no element holds (a boundary that is curved differently on the two meshes) takes the nearest point of the nearest element and is
COUNTED: the report says how many and how far.

`solve_coupled(members, options)` runs the members in the order the physics needs (the heat problem first, then the stress problem that takes its temperature), hands
the fields over, and returns one result with the checks that must hold: nothing was extrapolated, every point was found, the temperature average on the receiving mesh
matches the sending one, the receiving analysis really used the field it was given.  A member is anything with the small interface of `Member` below (the windows of the
Workbench are wrapped in coupled_members.py; the tests use plain objects).  No Qt in this file.

A 2D fluid flow (the CFD) can take part as a third kind of member, role "fluid": with a structural analysis the pressure on the walls is handed to it as a load; with a thermal
analysis the two exchange heat through the walls they share (coupled_fluid.py: a loop that stops when the heat flux agrees on both sides); with both, the heat is exchanged first
and then the temperature and the pressure go to the structural analysis.
"""
import time

import numpy as np

KELVIN = 273.15


class CoupledError(Exception):
    """A coupled solve that cannot go on, in words the user can act on."""


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------------------- finding points in a mesh
class Locator:
    """Point location in a mesh of triangles (points (n, 2), simplices (m, 3)) or tetrahedra (points (n, 3), simplices (m, 4)); only the first d + 1 columns of
    `simplices` are used, so a quadratic element's corner nodes can come first and its mid-nodes after."""

    def __init__(self, points, simplices):
        from scipy.spatial import cKDTree
        P = np.asarray(points, float)
        self.d = P.shape[1]
        if self.d not in (2, 3):
            raise CoupledError("A field can only be handed over between meshes in two or three dimensions.")
        S = np.asarray(simplices)[:, :self.d + 1].astype(np.int64)
        self.P, self.S = P, S
        v0 = P[S[:, 0]]
        A = np.stack([P[S[:, i]] - v0 for i in range(1, self.d + 1)], axis=2)          # (m, d, d): the columns are the edges from vertex 0
        det = np.linalg.det(A)
        scale = np.median(np.abs(det[det != 0])) if np.any(det != 0) else 1.0
        self.good = np.abs(det) > 1e-12 * max(scale, 1e-300)
        Ainv = np.zeros_like(A)
        if np.any(self.good):
            Ainv[self.good] = np.linalg.inv(A[self.good])
        self.v0, self.Ainv = v0, Ainv
        self.centroid = P[S].mean(axis=1)
        self.tree = cKDTree(self.centroid[self.good]) if np.any(self.good) else None
        self.ids = np.nonzero(self.good)[0]
        h = np.linalg.norm(P[S[:, 1]] - P[S[:, 0]], axis=1)
        self.h = float(np.median(h)) if len(h) else 1.0

    def _try(self, X, k):
        """The best of the k elements whose centres are nearest to each point: (element, weights, smallest weight)."""
        n = len(X)
        k = min(k, len(self.ids))
        _dist, cand = self.tree.query(X, k=k)
        cand = np.asarray(cand).reshape(n, k)
        el = self.ids[cand]                                                              # (n, k) element numbers
        rel = X[:, None, :] - self.v0[el]                                                # (n, k, d)
        lam_tail = np.einsum("nkij,nkj->nki", self.Ainv[el], rel)                        # (n, k, d): weights of vertices 1..d
        lam = np.concatenate([1.0 - lam_tail.sum(axis=2, keepdims=True), lam_tail], axis=2)
        worst = lam.min(axis=2)                                                          # (n, k): negative = outside that element
        best = np.argmax(worst, axis=1)
        rows = np.arange(n)
        return el[rows, best], lam[rows, best], worst[rows, best]

    def locate(self, targets, k=24, tol=1e-7):
        """-> (element index (n,), barycentric weights (n, d + 1), outside (n,) bool, distance (n,)): for every target the element that holds it (the element whose
        smallest weight is largest), the weights, whether the target is outside every element (then the weights are those of the nearest point of the best element,
        clamped to the element) and how far outside in the units of the mesh.  A thin element can hold a point although its centre is far: the points that the nearest
        elements do not hold are searched again among more of them."""
        X = np.asarray(targets, float).reshape(-1, self.d)
        if self.tree is None:
            raise CoupledError("The mesh that sends the field has no usable element.")
        el_b, lam_b, worst_b = self._try(X, k)
        for wider in (4 * k, 16 * k, 64 * k):
            miss = np.nonzero(worst_b < -tol)[0]
            if len(miss) == 0 or k >= len(self.ids):
                break
            e2, l2, w2 = self._try(X[miss], wider)
            better = w2 > worst_b[miss]
            idx = miss[better]
            el_b[idx], lam_b[idx], worst_b[idx] = e2[better], l2[better], w2[better]
            k = wider
        outside = worst_b < -tol
        if np.any(outside):
            lc = np.clip(lam_b[outside], 0.0, None)                                       # the nearest point of the element: clamp and renormalise
            lam_b[outside] = lc / lc.sum(axis=1, keepdims=True)
        dist = np.where(outside, -worst_b * self.h, 0.0)                                  # (weights are lengths over the element size: a good estimate of the gap)
        return el_b, lam_b, outside, dist

    def interpolate(self, values, targets, k=24):
        """-> (values at the targets, info).  `values` is one number per point of the mesh."""
        v = np.asarray(values, float).reshape(-1)
        if len(v) != len(self.P):
            raise CoupledError(f"The field has {len(v)} values but its mesh has {len(self.P)} nodes.")
        el, lam, outside, dist = self.locate(targets, k=k)
        out = np.einsum("nk,nk->n", v[self.S[el]], lam)
        info = {"points": int(len(out)), "outside": int(outside.sum()), "max_gap": float(dist.max()) if len(dist) else 0.0, "direct": False}
        return out, info


def hand_over(src_points, src_simplices, src_values, targets, locator=None):
    """The field (one value per source node) at the points `targets`.  The same points in the same order (two analyses that meshed the same way) are handed over
    as they are.  -> (values, info) with info = {"points", "outside", "max_gap", "direct"}."""
    X = np.asarray(targets, float)
    P = np.asarray(src_points, float)
    v = np.asarray(src_values, float).reshape(-1)
    if X.shape == P.shape and np.array_equal(X, P):
        return v.copy(), {"points": int(len(X)), "outside": 0, "max_gap": 0.0, "direct": True}
    loc = locator or Locator(P, src_simplices)
    return loc.interpolate(v, X)


# ---------------------------------------------------------------------------------------------------------------------------- weights of a mesh
def lumped_weights(points, simplices, n=None):
    """The length / area / volume that every node of a mesh of triangles or tetrahedra stands for (an element's measure shared equally between its corners): the weights
    of an average over the mesh.  `n` = how many nodes to give a weight to (the mid-nodes of a quadratic mesh get none)."""
    P = np.asarray(points, float)
    d = P.shape[1]
    S = np.asarray(simplices)[:, :d + 1].astype(np.int64)
    v0 = P[S[:, 0]]
    A = np.stack([P[S[:, i]] - v0 for i in range(1, d + 1)], axis=2)
    meas = np.abs(np.linalg.det(A)) / (2.0 if d == 2 else 6.0)
    w = np.zeros(len(P) if n is None else n)
    for j in range(d + 1):
        np.add.at(w, S[:, j], meas / (d + 1))
    return w


# ---------------------------------------------------------------------------------------------------------------------------- the members
class Member:
    """What the loop needs of an analysis (the Workbench wraps its windows in this; a test uses a plain object).  Attributes: `dim` (2 or 3), `role` ("thermal" or
    "structural"), `label`.  Thermal: solve() -> result dict, temperature_field() -> (points, simplices, values, mean).
    Structural: solve(temperature_at) -> result dict, where temperature_at(points) -> the temperature (kelvin) at those points; the member calls it with the nodes of ITS mesh,
    and puts the mesh weights of those nodes (for the average check) in `last_weights` and their points in `last_points`.  With a fluid member the engine calls
    solve(temperature_at, cfd=info) where info = {"info": the CFD window's transfer_info(), "edges": the walls of the fluid, "shear": bool}; temperature_at is None when
    there is no thermal analysis; the member then puts what it loaded in `pressure_report()` -> {"edges", "force": (fx, fy) N per metre of depth, "same_geometry": bool}.
    Fluid: solve_flow(), coupled_keys(), h_iso(), profile(values), solve_temperature(Tw_at), pressure_info(), pressure_force(edges, shear) -> ((fx, fy), scale) with scale the sum
    of the sizes of the pressure forces of the wall segments, flow_summary(), T_in, see coupled_fluid.py.
    Thermal with a fluid: set_fluid(h_at, Tref_at, keys), wall_temperature_at(points) -> (values, gap), heat_to_fluid(), thickness.
    Every member may get `cancel` (a function) and `say` (a function(text, fraction)) from the engine to stay responsive during a long solve."""
    dim = 2
    role = ""
    label = ""
    cancel = None
    say = None

    def release(self):
        """Called when the solve is over (done, stopped or failed): takes back what the engine put into the window for it."""


def check(name, ok, detail, hard=False):
    return {"name": name, "ok": bool(ok), "detail": detail, "hard": bool(hard)}


def _temperature_to_structural(th, st, opt, tick, out, thermal_solved=False, cfd=None):
    """The heat problem (unless it is solved already), its temperature handed to the stress problem, the stress problem; the transfer and its checks go into `out`."""
    if not thermal_solved:
        tick(f"{th.label}: solving the heat problem", 0.05)
        t1 = time.monotonic()
        th.solve()
        out["thermal"] = {"seconds": time.monotonic() - t1}
    else:
        out.setdefault("thermal", {"seconds": 0.0})
    pts, simp, T_src, T_mean = th.temperature_field()
    T_src = np.asarray(T_src, float)
    if not np.all(np.isfinite(T_src)):
        raise CoupledError("The thermal analysis gave a temperature that is not finite: solve it on its own and check the conditions.")
    out["thermal"].update(T_min=float(T_src.min()), T_max=float(T_src.max()), T_mean=float(T_mean))
    loc = Locator(pts, simp)
    seen = {}

    def temperature_at(points):
        vals, info = hand_over(pts, simp, T_src, points, loc)
        seen.update(info)
        seen["mapped_min"], seen["mapped_max"] = float(vals.min()), float(vals.max())
        seen["points_at"], seen["vals"] = np.asarray(points, float), vals
        return vals
    tick(f"{st.label}: solving the stress problem with that temperature", 0.5 if cfd is None else 0.8)
    t2 = time.monotonic()
    sres = st.solve(temperature_at) if cfd is None else st.solve(temperature_at, cfd=cfd)
    out["structural"] = {"seconds": time.monotonic() - t2}
    if not seen:
        raise CoupledError("The structural analysis did not ask for the temperature: it was not solved as a thermal-stress problem.")
    tick("Checking the hand-over", 0.95)
    tr = {"name": "Thermal → Structural", "what": "temperature", "points": seen["points"], "outside": seen["outside"], "max_gap": seen["max_gap"], "direct": seen["direct"],
          "src_range": (float(T_src.min()), float(T_src.max())), "dst_range": (seen["mapped_min"], seen["mapped_max"])}
    span = max(float(T_src.max() - T_src.min()), 1e-9)
    eps = 1e-9 * max(1.0, abs(float(T_src.max())))
    out["transfers"].append(tr)
    out["checks"].append(check("Nothing extrapolated", tr["dst_range"][0] >= tr["src_range"][0] - eps and tr["dst_range"][1] <= tr["src_range"][1] + eps,
                               f"the temperature on the stress mesh runs from {tr['dst_range'][0] - KELVIN:.5g} to {tr['dst_range'][1] - KELVIN:.5g} degC, inside the "
                               f"{tr['src_range'][0] - KELVIN:.5g} .. {tr['src_range'][1] - KELVIN:.5g} degC of the heat problem", hard=True))
    out["checks"].append(check("Every point found", seen["outside"] == 0,
                               "all " + f"{seen['points']:,} nodes of the stress mesh lie inside the thermal mesh" if seen["outside"] == 0 else
                               f"{seen['outside']:,} of {seen['points']:,} nodes of the stress mesh lie outside the thermal mesh (up to {seen['max_gap']:.3g} of the mesh units); they took the "
                               "temperature of the nearest point. The two analyses should work on the same geometry"))
    w = getattr(st, "last_weights", None)
    if w is not None and getattr(st, "last_points", None) is not None and np.shape(w)[0] == seen["points"]:
        mean_dst = float(np.sum(np.asarray(w) * seen["vals"]) / np.sum(w))
        dev = abs(mean_dst - T_mean) / span
        tr["mean_dst"], tr["mean_src"] = mean_dst, float(T_mean)
        out["checks"].append(check("Average temperature kept", dev <= opt["tmean_tol"],
                                   f"{mean_dst - KELVIN:.5g} degC on the stress mesh, {T_mean - KELVIN:.5g} degC on the thermal mesh (difference {100 * dev:.2g} % of the temperature range)"))
    used = (sres or {}).get("thermal") if isinstance(sres, dict) else None
    if used is not None:
        ok = abs(used["T_min"] - tr["dst_range"][0]) <= 1e-6 * max(1.0, abs(tr["dst_range"][1])) and abs(used["T_max"] - tr["dst_range"][1]) <= 1e-6 * max(1.0, abs(tr["dst_range"][1]))
        out["checks"].append(check("Stress solve used the field", ok, f"it reports {used['T_min'] - KELVIN:.5g} .. {used['T_max'] - KELVIN:.5g} degC; it was given "
                                   f"{tr['dst_range'][0] - KELVIN:.5g} .. {tr['dst_range'][1] - KELVIN:.5g} degC", hard=True))
    return sres


def _finish(out, t0, tick):
    out["ok"] = all(c["ok"] for c in out["checks"] if c["hard"])
    out["seconds"] = time.monotonic() - t0
    tick("Done", 1.0)
    return out


def solve_coupled(members, options=None, progress=None, cancel=None):
    """Runs the members of one Coupled Physics block, all of the same dimension.  Thermal + Structural: the heat problem, the temperature handed to the stress problem, the stress
    problem.  With a fluid (2D): see `_solve_with_fluid`.
    options: {"tmean_tol": 0.02} (the average temperature on the receiving mesh may differ from the sending one by this fraction of the temperature range); with a fluid also
    "conj_tol", "conj_max", "q_tol" (coupled_fluid.py) and "pressure_tol" (the pressure force handed to the stress analysis against the fluid's, 0.02); "moves_flow" (the displacement
    of the structure moves the body in the flow, which is solved again round it: `_fsi_loop`) with "fsi_tol" (the displacement must change by less than this fraction between two
    passes, 0.01), "fsi_max" (the most passes, 12), "fsi_relax" (the first relaxation factor, 1) and "fsi_aitken" (True: the factor is worked out again after every pass).
    -> {"ok", "error", "passes": [...], "transfers": [...], "checks": [...], "thermal": {...}, "structural": {...}, "fluid": {...}, "seconds"}.  Raises Cancelled when cancel() says so;
    CoupledError (plain words) for a problem the user can fix; the checks that fail are in the result, with "ok" False when a hard one does."""
    opt = {"tmean_tol": 0.02, "conj_tol": 0.01, "conj_max": 25, "q_tol": 0.05, "pressure_tol": 0.02, "moves_flow": False, "fsi_tol": 0.01, "fsi_max": 12, "fsi_relax": 1.0, "fsi_aitken": True}
    opt.update(options or {})

    def tick(text, frac):
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None:
            progress(text, frac)
    fl, th, st = members.get("fluid"), members.get("thermal"), members.get("structural")
    for m_ in (fl, th, st):
        if m_ is not None:
            m_.cancel = (lambda: cancel is not None and cancel())
            m_.say = tick
    try:
        if fl is not None:
            return _solve_with_fluid(fl, th, st, opt, tick)
        if th is None or st is None:
            raise CoupledError("A Coupled Physics solve needs a Thermal analysis and a Structural analysis.")
        if th.dim != st.dim:
            raise CoupledError(f"The thermal analysis is {th.dim}D and the structural analysis is {st.dim}D: both must be of the same dimension.")
        t0 = time.monotonic()
        out = {"ok": True, "error": None, "passes": [], "transfers": [], "checks": [], "dim": th.dim}
        _temperature_to_structural(th, st, opt, tick, out)
        out["passes"].append({"pass": 1, "change": None, "note": "One way: the temperature does not depend on the stress, so one pass is the answer."})
        return _finish(out, t0, tick)
    finally:
        for m_ in (fl, th, st):
            if m_ is not None and hasattr(m_, "release"):                                  # (a member that is not a Member has nothing to give back)
                m_.release()


# ---------------------------------------------------------------------------------------------------------------------------- with a fluid
def _flow_checks(fl, flow, out):
    s = fl.flow_summary()
    out["fluid"].update(s)
    out["checks"].append(check("Flow settled", flow.get("status") == "converged",
                               f"the flow reached a steady state after {s.get('steps', '?')} steps" if flow.get("status") == "converged" else
                               f"the flow did NOT settle (status: {flow.get('status')}): what follows belongs to its last time step, not to a steady flow"))


def _fluid_thermal(fl, th, opt, tick, out):
    import coupled_fluid as cf
    try:
        r = cf.solve_fluid_thermal(fl, th, {"conj_tol": opt["conj_tol"], "conj_max": opt["conj_max"], "q_tol": opt["q_tol"]}, tick)
    except cf.FluidThermalError as ex:
        raise CoupledError(str(ex))
    flow = r["flow"]
    _flow_checks(fl, flow, out)
    hres = r["heat"]
    wall = [hres["walls"][k] for k in r["keys"]]
    Tw = np.concatenate([np.concatenate([w["T_a"], w["T_b"]]) for w in wall])
    out["fluid"].update(T_in=float(r["T_in"]), Tw_min=float(Tw.min()), Tw_max=float(Tw.max()), Tmin=float(hres["Tmin"]), Tmax=float(hres["Tmax"]), iterations=r["iterations"],
                        mismatch=r["mismatch"], Q_fluid=r["Q_fluid"], Q_solid=r["Q_solid"], history=r["history"], Pr=float(hres.get("Pr", float("nan"))),
                        balance=hres["balance"], notes=list(hres.get("notes", [])), h_max=r["h_max"])
    out["transfers"].append({"name": "Fluid ⇄ Thermal", "what": "heat exchange", "points": int(sum(len(w["T_a"]) for w in wall)), "outside": 0, "max_gap": max(r["gap_fluid"], r["gap_solid"]),
                             "direct": False, "src_text": f"{r['T_in'] - KELVIN:.5g} degC inlet", "dst_text": f"wall {Tw.min() - KELVIN:.5g} .. {Tw.max() - KELVIN:.5g} degC",
                             "src_range": (float(r["T_in"]), float(Tw.max())), "dst_range": (float(Tw.min()), float(Tw.max()))})
    out["checks"].append(check("Heat exchange converged", r["converged"],
                               f"the heat flux on the wall agrees on both sides to {100 * r['mismatch']:.2g} % after {r['iterations']} iterations (limit {100 * r['tol']:g} %)" if r["converged"] else
                               f"after {r['iterations']} iterations the heat flux still differs by {100 * r['mismatch']:.2g} % between the solid and the fluid (limit {100 * r['tol']:g} %): "
                               "raise the maximum number of iterations, or the two analyses do not describe the same wall", hard=True))
    out["checks"].append(check("Heat leaving the solid = heat entering the fluid", abs(r["Q_rel"]) <= r["q_tol"],
                               f"{r['Q_solid']:.5g} W leave the solid, {r['Q_fluid']:.5g} W enter the fluid (difference {100 * abs(r['Q_rel']):.2g} %, limit {100 * r['q_tol']:g} %)", hard=True))
    gap = max(r["gap_fluid"], r["gap_solid"])
    out["checks"].append(check("Every wall point found", gap <= 0.5,
                               "every point of the wall of one mesh found its place on the wall of the other" if gap <= 0.5 else
                               f"a wall point lies {gap:.2g} element sizes from the wall of the other mesh: the two analyses do not have the same wall there", hard=True))
    rel = abs(float(hres["balance"].get("relative", 0.0)))
    out["checks"].append(check("Fluid energy balance", rel <= 0.05,
                               f"the heat the walls give to the fluid and the heat the flow carries away differ by {100 * rel:.1f} % (limit 5 %)"))
    over = hres.get("overshoot")
    if over is not None:
        rng = max(out["fluid"]["Tw_max"], out["fluid"]["T_in"]) - min(out["fluid"]["Tw_min"], out["fluid"]["T_in"])
        out["checks"].append(check("Temperature inside the given range", rng <= 0 or over <= 0.02 * rng,
                                   f"the fluid temperature stays within {over:.2g} K of the range of the wall and inlet temperatures"))
    return r


def _pressure_to_structural(fl, st, th, opt, tick, out, thermal_solved):
    """The fluid pressure on the walls of the stress analysis (with the temperature when there is a thermal analysis)."""
    info = fl.pressure_info()
    cfd = {"info": info["info"], "edges": info["edges"], "shear": bool(opt.get("shear", False))}
    if th is not None:
        sres = _temperature_to_structural(th, st, opt, tick, out, thermal_solved=thermal_solved, cfd=cfd)
    else:
        tick(f"{st.label}: solving the stress problem with the fluid pressure", 0.8)
        t2 = time.monotonic()
        sres = st.solve(None, cfd=cfd)
        out["structural"] = {"seconds": time.monotonic() - t2}
    rep = st.pressure_report()
    edges = [tuple(k) for k in rep["edges"]]
    if not edges:
        raise CoupledError("The structural analysis got no fluid pressure: none of its edges is a wall of the fluid without a support. Check that the two analyses use the same sketch, "
                           "and that the edges the fluid pushes on are not held by a support.")
    F_cfd, scale = fl.pressure_force(edges, shear=bool(opt.get("shear", False)))
    F_cfd, F_fea = np.asarray(F_cfd, float), np.asarray(rep["force"], float)
    scale = max(float(scale), float(np.hypot(*F_cfd)), 1e-300)                     # (the resultant of a closed body can be near zero: the load carried is the scale)
    dev = float(np.hypot(*(F_fea - F_cfd))) / scale
    names = ", ".join(f"{k[0]} {k[1]}" for k in edges)
    out["transfers"].append({"name": "Fluid → Structural", "what": "pressure", "points": len(edges), "outside": 0, "max_gap": 0.0, "direct": False,
                             "src_text": f"force ({F_cfd[0]:.4g}, {F_cfd[1]:.4g}) N per metre of depth", "dst_text": f"force ({F_fea[0]:.4g}, {F_fea[1]:.4g}) N per metre of depth",
                             "unit": "edges", "edges": edges})
    out["checks"].append(check("Pressure force handed over", dev <= opt["pressure_tol"],
                               f"the stress analysis carries ({F_fea[0]:.4g}, {F_fea[1]:.4g}) N per metre of depth on {names}; the fluid pushes with ({F_cfd[0]:.4g}, {F_cfd[1]:.4g}) N "
                               f"there (difference {100 * dev:.2g} % of the pressure load carried, limit {100 * opt['pressure_tol']:g} %)", hard=True))
    if not rep.get("same_geometry", True):
        out["checks"].append(check("Same walls in both analyses", False, "some edges differ between the stress and the fluid sketch; the pressure was placed by position along the edge"))
    return sres


def _one_pass(fl, th, st, opt, tick, out):
    """The flow (with the heat exchange when there is a thermal analysis) and the stress analysis loaded with its pressure (and the temperature)."""
    t1 = time.monotonic()
    if th is not None:
        r = _fluid_thermal(fl, th, opt, tick, out)
        out["fluid"]["seconds"] = time.monotonic() - t1
        out["thermal"] = {"seconds": out["fluid"]["seconds"]}
        pts, simp, T_src, T_mean = th.temperature_field()
        T_src = np.asarray(T_src, float)
        out["thermal"].update(T_min=float(T_src.min()), T_max=float(T_src.max()), T_mean=float(T_mean))
        out["passes"].append({"pass": r["iterations"], "change": r["mismatch"], "note": f"The fluid and the solid exchanged heat for {r['iterations']} iterations; the flow itself was solved once "
                                                                                       "(the temperature does not change the flow: no buoyancy)."})
    else:
        tick(f"{fl.label}: solving the flow", 0.1)
        flow = fl.solve_flow()
        out["fluid"] = {"seconds": time.monotonic() - t1}
        _flow_checks(fl, flow, out)
        out["passes"].append({"pass": 1, "change": None, "note": "One way: the pressure of the settled flow is the load of the stress analysis."})
    if st is not None:
        _pressure_to_structural(fl, st, th, opt, tick, out, thermal_solved=th is not None)


def _fsi_loop(fl, th, st, opt, tick, out):
    """The structure moves the flow.  Pass 1: the flow round the body as drawn, the stress analysis loaded with its pressure (and the temperature).  The displacement D of the stress
    analysis at the points of the outline then moves the body in the fluid window, which meshes it again and solves the flow round it; the stress analysis is loaded with that pressure,
    gives a new displacement, and so on (a fixed-point loop on D, relaxed: D <- D + w (D_new - D), w worked out by Aitken's rule from the last two residuals).  It stops when D_new differs from the D the flow
    was solved with by less than `fsi_tol` of the largest displacement.  The stress analysis stays linear (small displacements): the load of the moved flow is put on the edges as drawn.
    The last pass is the answer."""
    if st is None:
        raise CoupledError("The structure can only move the flow when a Static Structural analysis is wired in with the fluid flow.")
    if hasattr(fl, "check_movable"):
        fl.check_movable()
    bp = fl.boundary_points()
    P = np.asarray(bp["P"], float)
    size = float(fl.length_scale())
    negligible = 1e-6 * size                                                   # a structure that moves less than this does not move the flow (a millionth of the body is a small part of one element)
    floor = 1e-9 * size                                                        # a change smaller than this is noise
    tol, nmax = float(opt["fsi_tol"]), max(1, int(opt["fsi_max"]))
    omega = float(opt["fsi_relax"])
    D = np.zeros_like(P)
    R_prev = None
    hist, converged, last = [], False, None
    for it in range(1, nmax + 1):
        fl.set_shape(None if it == 1 else D)
        scratch = {"ok": True, "error": None, "passes": [], "transfers": [], "checks": [], "dim": fl.dim, "fluid": {}}

        def say(text, frac, it=it):
            tick(f"Pass {it} of at most {nmax}: {text}", (it - 1 + frac) / nmax)
        _one_pass(fl, th, st, opt, say, scratch)
        Dn, gap = st.displacement_at(P)
        Dn = np.asarray(Dn, float)
        umax = float(np.hypot(Dn[:, 0], Dn[:, 1]).max())
        step = float(np.hypot(Dn[:, 0] - D[:, 0], Dn[:, 1] - D[:, 1]).max())
        change = step / max(umax, floor)
        R = (Dn - D).ravel()                                                    # the residual: where the structure says the outline should be, against where the flow had it
        row = {"it": it, "change": change, "step": step, "umax": umax, "omega": omega, "gap": float(gap)}
        if hasattr(fl, "mesh_summary"):
            row["mesh"] = fl.mesh_summary()
        hist.append(row)
        last = (scratch, Dn, gap)
        if it == 1 and umax <= negligible:
            converged = True
            row["negligible"] = True
            break
        if it > 1 and step <= max(tol * umax, floor):
            converged = True
            break
        if opt.get("fsi_aitken", True) and R_prev is not None:                 # Aitken's dynamic relaxation: the factor that would have made the last two residuals cancel
            dR = R - R_prev
            den = float(dR @ dR)
            if den > 0.0:
                omega = float(np.clip(-omega * float(R_prev @ dR) / den, 0.05, 1.0))
        row["omega"] = omega                                                    # (the factor of the step taken after this pass)
        D = D + omega * (Dn - D)
        R_prev = R
    scratch, Dn, gap = last
    for key in ("checks", "transfers"):
        out[key] += scratch[key]
    for key in ("fluid", "thermal", "structural"):
        if key in scratch:
            out[key] = scratch[key]
    for h in hist:
        out["passes"].append({"pass": h["it"], "change": h["change"], "note": f"Pass {h['it']}: the largest displacement is {h['umax']:.4g}; it differs by {100 * h['change']:.3g} % of that from the one the flow was "
                                                                              f"solved with (relaxation {h['omega']:g})." if h["it"] > 1 else
                                                                              f"Pass 1: the flow round the body as drawn; the largest displacement is {h['umax']:.4g}."})
    umax = hist[-1]["umax"]
    out["fsi"] = {"converged": converged, "iterations": len(hist), "tol": tol, "history": hist, "umax": umax, "size": size, "gap": float(gap)}
    out["checks"].append(check("Moved flow converged", converged,
                               (f"the displacement changed by {100 * hist[-1]['change']:.2g} % between the last two passes (limit {100 * tol:g} %) after {len(hist)} passes"
                                if len(hist) > 1 else f"the structure moved less than {negligible:.2g} (a millionth of the body): it does not move the flow")
                               if converged else
                               f"after {len(hist)} passes the displacement still changes by {100 * hist[-1]['change']:.2g} % from one pass to the next (limit {100 * tol:g} %): "
                               "raise the number of passes, lower the relaxation, or the structure is too soft for the flow to hold it still", hard=True))
    out["checks"].append(check("Outline found on the stress mesh", gap <= 0.5,
                               "every point of the outline of the body lies on the stress mesh" if gap <= 0.5 else
                               f"a point of the outline lies {gap:.2g} element sizes from the stress mesh: the two analyses do not have the same body", hard=True))
    out["checks"].append(check("Displacement small enough for a linear stress analysis", umax <= 0.05 * size,
                               f"the largest displacement is {100 * umax / size:.2g} % of the size of the body" + ("" if umax <= 0.05 * size else
                                                                                                                  " (limit 5 %): the stress analysis assumes small displacements and the load of the moved flow is put on the edges as drawn")))
    return out


def _solve_with_fluid(fl, th, st, opt, tick):
    """A 2D fluid with a thermal analysis (they exchange heat), a structural analysis (it takes the pressure), or both (heat first, then the temperature and the pressure).  With
    opt["moves_flow"] the structure moves the body in the flow (`_fsi_loop`)."""
    others = [m for m in (th, st) if m is not None]
    if not others:
        raise CoupledError("A fluid flow needs a thermal analysis or a structural analysis to be coupled with.")
    for m in others:
        if m.dim != fl.dim:
            raise CoupledError(f"The fluid flow is {fl.dim}D and the {m.label} is {m.dim}D: Coupled Physics with a flow works in 2D for now, wire in 2D analyses.")
    t0 = time.monotonic()
    out = {"ok": True, "error": None, "passes": [], "transfers": [], "checks": [], "dim": fl.dim, "fluid": {}}
    if opt.get("moves_flow"):
        _fsi_loop(fl, th, st, opt, tick, out)
    else:
        _one_pass(fl, th, st, opt, tick, out)
    return _finish(out, t0, tick)
