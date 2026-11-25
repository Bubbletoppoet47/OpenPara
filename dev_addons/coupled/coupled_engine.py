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
    and puts the mesh weights of those nodes (for the average check) in `last_weights` and their points in `last_points`."""
    dim = 2
    role = ""
    label = ""


def check(name, ok, detail, hard=False):
    return {"name": name, "ok": bool(ok), "detail": detail, "hard": bool(hard)}


def solve_coupled(members, options=None, progress=None, cancel=None):
    """Runs a Thermal and a Structural member of the same dimension: the heat problem, the temperature handed to the stress problem, the stress problem.
    options: {"tmean_tol": 0.02} (the average temperature on the receiving mesh may differ from the sending one by this fraction of the temperature range).
    -> {"ok", "error", "passes": [...], "transfers": [...], "checks": [...], "thermal": {...}, "structural": {...}, "seconds"}.  Raises Cancelled when cancel() says so;
    CoupledError (plain words) for a problem the user can fix; the checks that fail are in the result, with "ok" False when a hard one does."""
    opt = {"tmean_tol": 0.02}
    opt.update(options or {})

    def tick(text, frac):
        if cancel is not None and cancel():
            raise Cancelled()
        if progress is not None:
            progress(text, frac)
    th, st = members.get("thermal"), members.get("structural")
    if th is None or st is None:
        raise CoupledError("A Coupled Physics solve needs a Thermal analysis and a Structural analysis.")
    if th.dim != st.dim:
        raise CoupledError(f"The thermal analysis is {th.dim}D and the structural analysis is {st.dim}D: both must be of the same dimension.")
    t0 = time.monotonic()
    out = {"ok": True, "error": None, "passes": [], "transfers": [], "checks": [], "dim": th.dim}
    tick(f"{th.label}: solving the heat problem", 0.05)
    t1 = time.monotonic()
    tres = th.solve()
    out["thermal"] = {"seconds": time.monotonic() - t1}
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
    tick(f"{st.label}: solving the stress problem with that temperature", 0.5)
    t2 = time.monotonic()
    sres = st.solve(temperature_at)
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
    out["passes"].append({"pass": 1, "change": None, "note": "One way: the temperature does not depend on the stress, so one pass is the answer."})
    out["ok"] = all(c["ok"] for c in out["checks"] if c["hard"])
    out["seconds"] = time.monotonic() - t0
    tick("Done", 1.0)
    return out

