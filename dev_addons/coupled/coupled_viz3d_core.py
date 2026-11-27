"""coupled_viz3d_core.py - the numbers behind the 3D picture of the Viz tab.  No Qt, no OpenGL: it takes the results of the LAST coupled solve of 3D analyses (the stress result: the nodes, the
triangles of the surface of the part, the displacement of every node, von Mises stress; the heat result: the temperature) and makes what the picture is drawn from: the surface of the part
with a temperature, a displacement and a von Mises stress at every vertex, its sharp edges, the camera, and a depth-correct software rasteriser (a z-buffer in numpy) that fills the triangles
with smooth colours and a little shading.  A test can look at every one of them.

Nothing is solved here and nothing is written back: the picture shows what the solve gave.  Lengths are in mm, the temperature in degC, the stress in MPa (the solvers' own units).

The animation is the one of the 2D picture (coupled_viz_core: 120 frames at 24 frames per second; the body is bent from nothing to its solved shape over the first half, smooth, and stays
there for the second half); the camera is the same in every frame, the view that was set, and the last frame is the still picture.
The displacement is far smaller than the part, so the shape is drawn `exaggeration` times larger than it is; the default is the factor that makes the largest displacement 8 % of the size of the
part (`auto_exaggeration`), and the picture says which factor it used.  The colours are the solved fields, except the displacement colour, which grows with the bend."""
import numpy as np

import coupled_viz_core as V

DEFAULTS3 = {"auto_fraction": 0.08, "feature_deg": 30.0, "azimuth": -35.0, "elevation": 25.0, "ambient": 0.55, "light": (-0.35, 0.45, 0.82), "max_exaggeration": 10000.0}
# the colourings, one at a time: key, name in the panel, title of the colour bar, colour map
FIELDS = (("T", "Temperature", "Temperature (degC)", "inferno"), ("u", "Displacement", "Displacement (mm)", "viridis"), ("vm", "Von Mises stress", "Von Mises stress (MPa)", "viridis"))
VIEWS = {"Isometric": (-35.0, 25.0), "Front": (-90.0, 0.0), "Right": (0.0, 0.0), "Top": (-90.0, 89.0)}


# ------------------------------------------------------------------------------------------------------------------------------ the surface
def surface_triangles(surface):
    """The triangles (M, 3) of the surface of the part from the faces of the stress mesh ({face id: (m, 3) or (m, 6) node indices}); a 6-node triangle is cut into four through its mid-nodes."""
    import coupled_surface as cs
    parts = [cs.split_triangles(t) for _f, t in sorted(surface.items(), key=lambda kv: str(kv[0])) if len(t)]
    return np.vstack(parts).astype(np.int64) if parts else np.zeros((0, 3), np.int64)


def surface_temperature(thermal, P):
    """The temperature (degC) of the heat result at the points P (n, 3) mm of the surface of the part, and how far the farthest of them lies from the surface of the heat mesh (in element sizes)."""
    import coupled_surface as cs
    mesh = thermal["mesh"]
    fids = list((mesh.get("ftri") or mesh.get("faces") or {}).keys())
    tris = cs.faces_triangles(mesh, fids)
    if not len(tris):
        raise ValueError("The heat mesh has no surface to take the temperature from.")
    loc = cs.SurfaceLocator(np.asarray(thermal["nodes"], float), tris)
    vals, info = loc.interpolate(np.asarray(thermal["T"], float), np.asarray(P, float))
    return np.asarray(vals, float) - 273.15, float(info["max_gap"]) / max(loc.h, 1e-300)


def feature_edges(X, tris, degrees=None):
    """The edges (E, 2) that show the shape of the part: those that belong to one triangle only (the rim of an open surface) and those where the two triangles meet at an angle of more than
    `degrees` (30 by default) between their normals."""
    deg = float(DEFAULTS3["feature_deg"] if degrees is None else degrees)
    t = np.asarray(tris, np.int64)
    if not len(t):
        return np.zeros((0, 2), np.int64)
    a, b, c = (X[t[:, i]] for i in range(3))
    nrm = np.cross(b - a, c - a)
    ln = np.linalg.norm(nrm, axis=1)
    nrm = nrm / np.maximum(ln, 1e-300)[:, None]
    e = np.stack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=1).reshape(-1, 2)
    owner = np.repeat(np.arange(len(t)), 3)
    lo, hi = e.min(axis=1), e.max(axis=1)
    n = int(t.max()) + 1
    key = lo * n + hi
    order = np.argsort(key, kind="stable")
    key_s, own_s = key[order], owner[order]
    first = np.concatenate([[True], key_s[1:] != key_s[:-1]])
    starts = np.flatnonzero(first)
    counts = np.diff(np.concatenate([starts, [len(key_s)]]))
    out = []
    cos_lim = np.cos(np.radians(deg))
    for s, c_ in zip(starts, counts):
        if c_ == 1:
            out.append(key_s[s])
        elif c_ == 2:
            n1, n2 = nrm[own_s[s]], nrm[own_s[s + 1]]
            if abs(float(np.dot(n1, n2))) < cos_lim:                         # (the sign of a normal depends on the order of the corners: the angle is of the planes)
                out.append(key_s[s])
    if not out:
        return np.zeros((0, 2), np.int64)
    k = np.asarray(out, np.int64)
    return np.stack([k // n, k % n], axis=1)


def auto_exaggeration(X, U, fraction=None):
    """The factor that makes the largest displacement `fraction` (8 %) of the largest size of the part, rounded to two figures and kept between 1 and 10000."""
    fr = float(DEFAULTS3["auto_fraction"] if fraction is None else fraction)
    size = float(np.ptp(X, axis=0).max()) if len(X) else 0.0
    umax = float(np.linalg.norm(U, axis=1).max()) if len(U) else 0.0
    if size <= 0 or umax <= 0:
        return 1.0
    f = fr * size / umax
    f = float(np.clip(f, 1.0, DEFAULTS3["max_exaggeration"]))
    mag = 10 ** (np.floor(np.log10(f)) - 1)
    return float(max(1.0, np.round(f / mag) * mag))


def build3d(nodes, surface, u, vm=None, temperature=None, options=None):
    """Everything the 3D picture is drawn from.
    nodes (n, 3) mm and u (n, 3) mm of the stress mesh, surface: its faces; vm (n,) MPa per node or None; temperature: None, or a function (points (m, 3) mm) -> degC.
    -> {"kind": "body3d", "X", "U", "tris", "T", "umag", "vm", "ranges": {"T"|"u"|"vm": (lo, hi)}, "edges", "centre", "radius", "exaggeration" (the automatic one), "options"}."""
    opt = dict(DEFAULTS3, frames=V.DEFAULTS["frames"])
    opt.update(options or {})
    nodes, u = np.asarray(nodes, float), np.asarray(u, float)
    tris = surface_triangles(surface)
    if not len(tris):
        raise ValueError("The stress result has no surface to draw.")
    used = np.unique(tris)
    remap = -np.ones(len(nodes), np.int64)
    remap[used] = np.arange(len(used))
    X, U = nodes[used], u[used]
    T = None
    if temperature is not None:
        T = np.asarray(temperature(X), float)
        if T.ndim == 2:
            T = T[:, 0]
    umag = np.linalg.norm(U, axis=1)
    vmv = None if vm is None else np.asarray(vm, float)[used]
    ranges = {"u": (0.0, float(umag.max()))}
    if T is not None:
        ranges["T"] = (float(T.min()), float(T.max()))
    if vmv is not None:
        ranges["vm"] = (float(vmv.min()), float(vmv.max()))
    t2 = remap[tris]
    centre = (X.min(axis=0) + X.max(axis=0)) / 2.0
    exa = auto_exaggeration(X, U)
    reach = X + exa * U
    pts = np.vstack([X, reach])
    radius = float(np.linalg.norm(pts - centre, axis=1).max())
    return {"kind": "body3d", "X": X, "U": U, "tris": t2, "T": T, "umag": umag, "vm": vmv, "ranges": ranges, "edges": feature_edges(X, t2, opt["feature_deg"]), "centre": centre,
            "radius": max(radius, 1e-9), "exaggeration": exa, "options": opt}


def available_fields(data):
    """[(key, name, title, colour map)] of the colourings this solve has (the displacement always; the temperature when there is a heat result; the stress when the result has it)."""
    return [f for f in FIELDS if f[0] == "u" or data["ranges"].get(f[0]) is not None]


def field_values(data, key, k=None, n=None):
    """The values of a colouring at the vertices in frame k: the displacement colour grows with the bend, the others are the solved field."""
    if key == "u":
        return data["umag"] * (V.bend_at(k, n) if k is not None else 1.0)
    return {"T": data["T"], "vm": data["vm"]}[key]


def frame_positions(data, k, exaggeration=None, n=None):
    """The vertices (n, 3) in frame k: the part as it is, moved by `bend x exaggeration x displacement`; and the bend (0 .. 1)."""
    ex = float(data["exaggeration"] if exaggeration is None else exaggeration)
    n = int(n or data["options"]["frames"])
    b = V.bend_at(k, n)
    return data["X"] + b * ex * data["U"], b


def reach_radius(data, exaggeration=None):
    """The radius of a ball round the middle of the part that holds it, rest and bent (bent by the whole exaggerated displacement): what the picture is fitted to, so that the part does not
    change size while it bends."""
    ex = float(data["exaggeration"] if exaggeration is None else exaggeration)
    memo = data.setdefault("_reach", {})
    if ex not in memo:
        c = data["centre"]
        memo[ex] = max(float(np.linalg.norm(data["X"] - c, axis=1).max()), float(np.linalg.norm(data["X"] + ex * data["U"] - c, axis=1).max()), 1e-9)
    return memo[ex]


def bend_reach3d(data, k=None, exaggeration=None, n=None):
    """The largest displacement (mm, the real one: the exaggeration taken out again) of a vertex in frame k (the last frame by default); 0 when the part has not bent yet."""
    n = int(n or data["options"]["frames"])
    k = n if k is None else k
    ex = float(data["exaggeration"] if exaggeration is None else exaggeration)
    P, b = frame_positions(data, k, ex, n)
    if b <= 0.0 or ex <= 0.0:
        return 0.0
    return float(np.linalg.norm((P - data["X"]) / (b * ex), axis=1).max())


# ------------------------------------------------------------------------------------------------------------------------------ heat-flux tracers (inside the part)
# The 3D heat result holds one heat-flux vector for every tetrahedron.  The tracers are made as the 2D ones are (coupled_viz_core: heat_lines, time_coordinate, laps_for): lines that start on the
# faces where heat enters the part, spaced so that every line stands for the same share of the heat that enters, and follow the flux until it leaves the part; particles travel along them, faster
# where the flux is stronger (a display, not a real speed).  The lines lie INSIDE the part, so the picture draws the surface faded while they are on.  In the animation the lines are carried with
# the bend of the part: their displacement is blended from the nearest points of the surface (the stress result gives the displacement of the surface vertices that are drawn), which is an
# approximation made for the picture only.
NO_FLOW = 1e-3                                           # a flux below this fraction of the strong flux is "no heat flow" (as in the 2D picture)
SEED_BLEND = 0.02                                        # a seed is put this far (of the way) from its face to the middle of its tetrahedron
SHELL_OPACITY = 0.42                                     # how solid the surface is drawn while the tracers are on
CANDIDATES3 = 32                                         # tetrahedra tried (nearest centres first) when looking for the one that holds a point


class FluxField3D:
    """The tetrahedra of the heat analysis (`nodes` (n, 3) and `tets` (m, 4): the corners) with one heat-flux vector each.  Finds the tetrahedron that holds a point, gives the direction of the
    heat there, and where heat enters the part.  Duck-typed like the 2D thermal_flow.FluxField: flux_at, direction, inlet_seeds, random_points, size, qref."""

    def __init__(self, nodes, tets):
        from scipy.spatial import cKDTree
        P = np.asarray(nodes, float)[:, :3]
        T = np.asarray(tets, np.int64)[:, :4]
        v = P[T]                                                                  # (m, 4, 3)
        self.v = v
        M = np.stack([v[:, 1] - v[:, 0], v[:, 2] - v[:, 0], v[:, 3] - v[:, 0]], axis=2)       # (m, 3, 3): the edges from corner 0 are the columns
        det = np.linalg.det(M)
        scale = np.maximum(np.abs(v.max(axis=1) - v.min(axis=1)).max(axis=1), 1e-300) ** 3
        self.good = np.abs(det) > 1e-12 * scale                                   # a tetrahedron without volume holds nothing
        self.Minv = np.linalg.inv(np.where(self.good[:, None, None], M, np.eye(3)))
        self.vol = np.where(self.good, np.abs(det) / 6.0, 0.0)
        self.cen = v.mean(axis=1)
        self.tree = cKDTree(self.cen)
        pts = v.reshape(-1, 3)
        self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
        self.size = float(np.ptp(pts, axis=0).max())
        self.q = np.zeros((len(v), 3))
        self.qref = 0.0
        self._boundary_faces(T)
        self._inlet_w = np.zeros(len(self.b_area))

    def _boundary_faces(self, T):
        """The faces that belong to one tetrahedron only (the surface of the part): the tetrahedron, the three corners, the area, the inward unit normal and the middle."""
        m = len(T)
        corners = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
        F = np.concatenate([T[:, c] for c in corners])                            # (4m, 3)
        owner = np.tile(np.arange(m), 4)
        key = np.sort(F, axis=1)
        _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        only = cnt[inv.reshape(-1)] == 1
        own = owner[only]
        P = np.concatenate([self.v[:, list(c)] for c in corners])[only]           # (k, 3, 3): the corners of each boundary face
        n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ln = np.linalg.norm(n, axis=1)
        n = n / np.maximum(ln, 1e-300)[:, None]
        mid = P.mean(axis=1)
        flip = np.sum(n * (self.cen[own] - mid), axis=1) < 0
        n[flip] = -n[flip]
        self.b_tet, self.b_P, self.b_area, self.b_n, self.b_mid = own, P, 0.5 * ln, n, mid

    def set_flux(self, q, qref=None):
        """The heat flux of every tetrahedron (any unit, the same for all), (m, 3).  `qref` is the strong flux (default: the 95th percentile of the flux magnitudes)."""
        q = np.asarray(q, float)
        if q.shape != (len(self.v), 3):
            raise ValueError("one heat-flux vector for every tetrahedron is needed")
        self.q = q
        mag = np.linalg.norm(q, axis=1)
        if qref is None:
            qref = float(np.percentile(mag, 95)) if mag.size else 0.0
            qref = qref if qref > 0 else (float(mag.max()) if mag.size else 0.0)
        self.qref = float(qref)
        inflow = np.sum(q[self.b_tet] * self.b_n, axis=1)                         # the flux into the part through each surface face
        self._inlet_w = np.where(inflow > NO_FLOW * self.qref, inflow, 0.0) * self.b_area if self.qref > 0 else np.zeros(len(self.b_area))

    def _bary(self, pts, cand):
        """Barycentric coordinates (n, k, 4) of the points in the candidate tetrahedra (n, k)."""
        d = pts[:, None, :] - self.v[cand, 0]
        l123 = np.einsum("nkij,nkj->nki", self.Minv[cand], d)
        return np.concatenate([1.0 - l123.sum(axis=2, keepdims=True), l123], axis=2)

    def locate(self, pts, with_bary=False):
        """The tetrahedron that holds each point (-1: none).  `pts` (n, 3).  With with_bary also the barycentric coordinates (n, 4) in it."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        n = len(pts)
        if n == 0:
            return (np.zeros(0, np.int64), np.zeros((0, 4))) if with_bary else np.zeros(0, np.int64)
        elem = -np.ones(n, np.int64)
        bary = np.zeros((n, 4))
        todo = np.arange(n)
        for k in (min(CANDIDATES3, len(self.v)), min(8 * CANDIDATES3, len(self.v))):       # (the second, wider try is for the points of long thin tetrahedra)
            if not len(todo):
                break
            _, cand = self.tree.query(pts[todo], k=k)
            cand = np.asarray(cand).reshape(len(todo), -1)
            lam = self._bary(pts[todo], cand)
            ok = (lam >= -1e-9).all(axis=2) & self.good[cand]
            first = ok.argmax(axis=1)
            rows = np.arange(len(todo))
            hit = ok[rows, first]
            elem[todo[hit]] = cand[rows[hit], first[hit]]
            bary[todo[hit]] = lam[rows[hit], first[hit]]
            todo = todo[~hit]
        return (elem, bary) if with_bary else elem

    def flux_at(self, pts):
        """-> (q (n, 3), inside (n,) bool): the heat flux vector of the tetrahedron that holds each point."""
        elem = self.locate(pts)
        inside = elem >= 0
        q = np.zeros((len(elem), 3))
        q[inside] = self.q[elem[inside]]
        return q, inside

    def direction(self, pts):
        """-> (unit direction (n, 3) times the speed ratio, inside (n,)): where the heat goes at each point and how strongly (flux over the strong flux, at most the 2D picture's largest ratio); no
        motion where the flux is below NO_FLOW of the strong flux."""
        q, inside = self.flux_at(pts)
        mag = np.linalg.norm(q, axis=1)
        out = np.zeros_like(q)
        if self.qref > 0:
            move = inside & (mag > NO_FLOW * self.qref)
            out[move] = q[move] / mag[move][:, None] * np.minimum(V.HEAT_RATIO_MAX, mag[move] / self.qref)[:, None]
        return out, inside

    def scalar_at(self, values, pts):
        """A nodal scalar (n_nodes values given for the corners as `values` (m, 4): the value at the 4 corners of every tetrahedron) interpolated linearly at the points: -> (n,), NaN outside."""
        elem, lam = self.locate(pts, with_bary=True)
        out = np.full(len(elem), np.nan)
        ok = elem >= 0
        out[ok] = np.sum(np.asarray(values)[elem[ok]] * lam[ok], axis=1)
        return out

    def inlet_seeds(self, n):
        """n points on the faces where heat enters the part, so that each stands for the same share of the heat that enters (faces chosen along the running total of the heat entering through
        them, in the order of the faces; the place on a face is a fixed low-discrepancy point), a little way in.  The same every time.  None when no heat enters through a face."""
        tot = float(self._inlet_w.sum())
        if n <= 0 or tot <= 0:
            return None
        cw = np.cumsum(self._inlet_w) / tot
        u = (np.arange(n) + 0.5) / n
        e = np.minimum(np.searchsorted(cw, u, side="right"), len(cw) - 1)
        i = np.arange(n)
        r1, r2 = (0.5 + i * 0.7548776662466927) % 1.0, (0.5 + i * 0.5698402909980532) % 1.0           # (the R2 sequence)
        s = np.sqrt(r1)
        lam = np.stack([1.0 - s, s * (1.0 - r2), s * r2], axis=1)
        on_face = np.einsum("nk,nkj->nj", lam, self.b_P[e])
        return (1.0 - SEED_BLEND) * on_face + SEED_BLEND * self.cen[self.b_tet[e]]

    def random_points(self, n, rng):
        """n points spread evenly over the volume of the part."""
        w = self.vol / self.vol.sum()
        idx = rng.choice(len(self.v), size=n, p=w)
        u = np.sort(rng.random((n, 3)), axis=1)
        lam = np.stack([u[:, 0], u[:, 1] - u[:, 0], u[:, 2] - u[:, 1], 1.0 - u[:, 2]], axis=1)
        return np.einsum("nk,nkj->nj", lam, self.v[idx])


def displacement_at_points(X, U, pts, k=4):
    """The displacement (mm) at points inside the part, blended from the k nearest of the surface vertices X (n, 3) that have the displacement U (n, 3): inverse distance squared."""
    from scipy.spatial import cKDTree
    pts = np.asarray(pts, float)
    kk = min(int(k), len(X))
    d, idx = cKDTree(X).query(pts, k=kk)
    d, idx = np.asarray(d).reshape(len(pts), -1), np.asarray(idx).reshape(len(pts), -1)
    w = 1.0 / (d * d + 1e-12)
    w = w / w.sum(axis=1, keepdims=True)
    return np.einsum("nk,nkj->nj", w, np.asarray(U, float)[idx])


def build_tracers(field, X, U, options=None):
    """The heat-flux tracers of a 3D part: `field` a FluxField3D with its heat flux set (its coordinates in mm), X (n, 3) and U (n, 3) the vertices of the surface that is drawn and their
    displacement (mm).  -> {"lines", "cum", "length", "starts", "laps", "disp" (the displacement of every point of every line), "heat": {"how", "qref", "period", "wanted"}, "options"}."""
    opt = dict(V.DEFAULTS, **V.HEAT_DEFAULTS)
    opt.update(options or {})
    lines, how = V.heat_lines(field, int(opt["lines"]), max_steps=opt["max_steps"])
    cums = [V.time_coordinate(ln, V.heat_ratio(field, ln, opt["ratio_min"]), opt["ratio_min"]) for ln in lines]
    lengths = [float(c[-1]) for c in cums]
    period = max(lengths, default=0.0)
    opt["trail"] = float(opt["trail_frac"]) * period
    disp = [displacement_at_points(X, U, ln) for ln in lines]
    return {"lines": lines, "cum": cums, "length": lengths, "starts": V.particle_starts(lengths, opt["per_line"], opt["seed"]), "laps": V.laps_for(lengths, opt["max_laps"]), "disp": disp,
            "heat": {"how": how, "qref": float(field.qref), "period": period, "wanted": int(opt["lines"])}, "options": opt}


def tracer_state(tr, k, exaggeration, n=None):
    """What the tracers look like in frame k (1 .. n): {"lines": [(m, 3)] (carried with the bend: moved by bend x exaggeration x their displacement), "particles": (p, 3), "tails": [(t, 3)]}.
    A particle goes along its line `laps` times in the whole animation, so the last frame has every particle where the first has it."""
    opt = tr["options"]
    n = int(n or V.DEFAULTS["frames"])
    b = V.bend_at(k, n)
    f = b * float(exaggeration)
    lines, parts, tails = [], [], []
    for line, cum, L, st, lp, dsp in zip(tr["lines"], tr["cum"], tr["length"], tr["starts"], tr["laps"], tr["disp"]):
        P = line + f * dsp
        lines.append(P)
        for s0 in st:
            s = (s0 + lp * (k / n) * L) % L
            parts.append([float(np.interp(s, cum, P[:, j])) for j in range(3)])
            ss = np.clip(s - np.linspace(0.0, float(opt["trail"]), int(opt["tail_points"])), 0.0, None)
            tails.append(np.stack([np.interp(ss, cum, P[:, j]) for j in range(3)], axis=1))
    return {"lines": lines, "particles": np.array(parts).reshape(-1, 3), "tails": tails}


def tracer_gap(tr, ka, kb, exaggeration, n=None):
    """The largest distance (mm) that a particle is apart between frame ka and frame kb, seen without the bend (the bend of the lines moves them too).  Between the last frame and frame 0: 0."""
    a = tracer_state(tr, ka, 0.0, n)["particles"]
    b = tracer_state(tr, kb, 0.0, n)["particles"]
    return float(np.linalg.norm(a - b, axis=1).max()) if len(a) else 0.0


# ------------------------------------------------------------------------------------------------------------------------------ the camera
class Camera:
    """An orthographic camera that turns round the middle of the part: `azimuth` and `elevation` in degrees (z is up), `zoom` 1 = the whole part (with its bent shape) fits the picture."""

    def __init__(self, azimuth=None, elevation=None, zoom=1.0):
        self.azimuth = float(DEFAULTS3["azimuth"] if azimuth is None else azimuth)
        self.elevation = float(DEFAULTS3["elevation"] if elevation is None else elevation)
        self.zoom = float(zoom)
        self.pan = np.zeros(2)

    def reset(self):
        self.azimuth, self.elevation, self.zoom = DEFAULTS3["azimuth"], DEFAULTS3["elevation"], 1.0
        self.pan = np.zeros(2)

    def turn(self, d_az, d_el):
        self.azimuth = (self.azimuth + float(d_az) + 180.0) % 360.0 - 180.0
        self.elevation = float(np.clip(self.elevation + float(d_el), -89.0, 89.0))

    def look(self, name):
        self.azimuth, self.elevation = VIEWS[name]

    def matrix(self):
        """Rows: the right, up and toward-the-viewer axes of the picture, in the axes of the part."""
        az, el = np.radians(self.azimuth), np.radians(self.elevation)
        d = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
        right = np.cross([0.0, 0.0, 1.0], d)
        right = right / np.linalg.norm(right)
        up = np.cross(d, right)
        return np.stack([right, up, d])


class Screen:
    """A camera on a picture of w x h pixels: `project(points)` -> (x, y, depth) with y down and a larger depth nearer to the viewer."""

    def __init__(self, camera, centre, radius, w, h, margin=0.9):
        self.R = camera.matrix()
        self.centre = np.asarray(centre, float)
        self.w, self.h = int(w), int(h)
        self.s = float(margin) * min(w, h) / (2.0 * radius) * camera.zoom
        self.o = np.array([w / 2.0 + camera.pan[0], h / 2.0 + camera.pan[1]])

    def project(self, P):
        q = (np.asarray(P, float) - self.centre) @ self.R.T
        return np.stack([self.o[0] + self.s * q[:, 0], self.o[1] - self.s * q[:, 1], q[:, 2]], axis=1)

    def normals(self, P, tris):
        """Unit normals of the triangles in the axes of the picture (z toward the viewer): the shading uses their direction, not their sign."""
        q = (np.asarray(P, float) - self.centre) @ self.R.T
        a, b, c = (q[tris[:, i]] for i in range(3))
        n = np.cross(b - a, c - a)
        return n / np.maximum(np.linalg.norm(n, axis=1), 1e-300)[:, None]


# ------------------------------------------------------------------------------------------------------------------------------ the rasteriser
def shade_of(normals, light=None, ambient=None):
    """The brightness (0 .. 1) of every triangle from its normal in the axes of the picture: ambient + diffuse, the same from both sides."""
    L = np.asarray(DEFAULTS3["light"] if light is None else light, float)
    L = L / np.linalg.norm(L)
    amb = float(DEFAULTS3["ambient"] if ambient is None else ambient)
    return amb + (1.0 - amb) * np.abs(normals @ L)


def raster3d(scr, P, tris, vals, lo, hi, table, shade, chunk=1_500_000):
    """The triangles of the part filled with colours, nearest first (a z-buffer): vals per vertex (smooth), `table` the 256 colours (uint8, 256 x 3) of the colour map, `shade` per triangle.
    -> (img (h, w, 4) uint8, RGBA, transparent where there is no triangle; depth (h, w) float, -inf where there is none)."""
    w, h = scr.w, scr.h
    S = scr.project(P)
    tris = np.asarray(tris, np.int64)
    A, B, C = S[tris[:, 0]], S[tris[:, 1]], S[tris[:, 2]]
    xs = np.stack([A[:, 0], B[:, 0], C[:, 0]], axis=1)
    ys = np.stack([A[:, 1], B[:, 1], C[:, 1]], axis=1)
    x0 = np.floor(xs.min(axis=1) - 0.5).astype(np.int64)
    x1 = np.ceil(xs.max(axis=1) - 0.5).astype(np.int64)
    y0 = np.floor(ys.min(axis=1) - 0.5).astype(np.int64)
    y1 = np.ceil(ys.max(axis=1) - 0.5).astype(np.int64)
    x0, y0 = np.maximum(x0, 0), np.maximum(y0, 0)
    x1, y1 = np.minimum(x1, w - 1), np.minimum(y1, h - 1)
    det = (B[:, 1] - C[:, 1]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 1] - C[:, 1])
    keep = (x1 >= x0) & (y1 >= y0) & (np.abs(det) > 1e-12)
    zbuf = np.full(w * h, -np.inf)
    vbuf = np.zeros(w * h)
    sbuf = np.zeros(w * h)
    vv = np.asarray(vals, float)
    idx = np.flatnonzero(keep)
    if len(idx):
        side = np.maximum(x1[idx] - x0[idx], y1[idx] - y0[idx]) + 1
        cls = np.ceil(np.log2(np.maximum(side, 1))).astype(np.int64)                      # (the triangles are done in groups of about the same size on the screen)
        for c_ in np.unique(cls):
            ids = idx[cls == c_]
            s = int(2 ** c_)
            per = max(1, int(chunk // (s * s)))
            for i0 in range(0, len(ids), per):
                part = ids[i0:i0 + per]
                _fragments(part, s, A, B, C, det, x0, y0, x1, y1, tris, vv, shade, w, zbuf, vbuf, sbuf)
    img = np.zeros((h * w, 4), np.uint8)
    seen = np.isfinite(zbuf)
    span = (hi - lo) if hi > lo else 1.0
    ci = np.clip(np.round((vbuf[seen] - lo) / span * 255.0), 0, 255).astype(np.int64)
    rgb = table[ci].astype(float) * np.clip(sbuf[seen], 0.0, 1.0)[:, None]
    img[seen, :3] = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    img[seen, 3] = 255
    return img.reshape(h, w, 4), zbuf.reshape(h, w)


def _fragments(ids, s, A, B, C, det, x0, y0, x1, y1, tris, vv, shade, w, zbuf, vbuf, sbuf):
    """The pixels of the triangles `ids` (each in a box of at most s x s pixels), written into the z-buffer where they are nearer than what is there."""
    m = len(ids)
    ar = np.arange(s)
    gx = (x0[ids][:, None, None] + ar[None, None, :]).astype(float) + 0.5
    gy = (y0[ids][:, None, None] + ar[None, :, None]).astype(float) + 0.5
    a, b, c = A[ids], B[ids], C[ids]
    d = det[ids][:, None, None]
    ax, ay = a[:, 0][:, None, None], a[:, 1][:, None, None]
    bx, by = b[:, 0][:, None, None], b[:, 1][:, None, None]
    cx, cy = c[:, 0][:, None, None], c[:, 1][:, None, None]
    l1 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / d
    l2 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / d
    l3 = 1.0 - l1 - l2
    eps = 1e-7
    inside = (l1 >= -eps) & (l2 >= -eps) & (l3 >= -eps) & (gx < (x1[ids][:, None, None] + 1.0)) & (gy < (y1[ids][:, None, None] + 1.0))
    if not inside.any():
        return
    t_, r_, q_ = np.nonzero(inside)                                                  # triangle in the group, row, column
    L1, L2, L3 = l1[t_, r_, q_], l2[t_, r_, q_], l3[t_, r_, q_]
    tid = ids[t_]
    tv = tris[tid]
    z = L1 * A[tid, 2] + L2 * B[tid, 2] + L3 * C[tid, 2]
    val = L1 * vv[tv[:, 0]] + L2 * vv[tv[:, 1]] + L3 * vv[tv[:, 2]]
    px = (y0[tid] + r_) * w + (x0[tid] + q_)
    order = np.lexsort((-z, px))                                                     # per pixel: the nearest fragment first
    px_s = px[order]
    first = np.concatenate([[True], px_s[1:] != px_s[:-1]])
    sel = order[first]
    p = px[sel]
    better = z[sel] > zbuf[p]
    sel, p = sel[better], p[better]
    zbuf[p] = z[sel]
    vbuf[p] = val[sel]
    sbuf[p] = shade[tid[sel]]


def edge_visible(scr, zbuf, P, edges, tol=None):
    """Which of the edges (E, 2) can be seen: the middle of the edge is not behind what the z-buffer holds there (a little room is given: the edge lies on the surface)."""
    if not len(edges):
        return np.zeros(0, bool)
    S = scr.project(P)
    mid = (S[edges[:, 0]] + S[edges[:, 1]]) / 2.0
    ix = np.clip(np.floor(mid[:, 0]).astype(np.int64), 0, scr.w - 1)
    iy = np.clip(np.floor(mid[:, 1]).astype(np.int64), 0, scr.h - 1)
    z = np.full(len(edges), -np.inf)
    for dy in (-1, 0, 1):                                                           # (an edge on the rim of the part lies between two pixels: the nearest of the nine round it counts)
        for dx in (-1, 0, 1):
            z = np.maximum(z, zbuf[np.clip(iy + dy, 0, scr.h - 1), np.clip(ix + dx, 0, scr.w - 1)])
    room = (0.02 if tol is None else tol) * (float(np.ptp(S[:, 2])) + 1e-12)
    return np.isfinite(z) & (mid[:, 2] >= z - room)


def axes_triad(camera):
    """The three axes of the part (x, y, z) as drawn from this camera: [(name, (dx, dy) in the picture with y down, length 0 .. 1)] for the little triad in the corner."""
    R = camera.matrix()
    out = []
    for i, name in enumerate("xyz"):
        v = R[:, i]
        out.append((name, (float(v[0]), float(-v[1])), float(np.hypot(v[0], v[1]))))
    return out
