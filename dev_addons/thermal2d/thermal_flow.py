"""thermal_flow.py - where the heat goes: moving tracer particles and arrows along the heat flux of a thermal result (no Qt).

Display only, nothing here is part of the result.  The heat flux q = -k grad T of a result is one vector for every drawing triangle (W/m2).

The tracers are made like the tracer particles of the 2D CFD (cfd_tab.py), with the heat flux where the CFD has the velocity: 700 particles, a trail of
7 points, a step every 30 ms of 0.03 s of display time, the midpoint rule, a speed in proportion to the flux over a reference flux (the CFD: the speed
over the free-stream speed), a particle that leaves the drawing or is older than 14 s starts again with an age of 0 to 3 s.  The CFD starts them again at
its inlets; here they start again at the edges where heat enters the body (in proportion to the heat entering there), or, if no heat enters through an
edge (heat made inside), anywhere in the drawing.  The reference flux is the strong flux of the picture (see reference_flux); in the CFD the speed is a real
one, here it only shows how the flux compares.  So the picture shows where the heat goes and how strongly compared with the strong areas.
The arrows are drawn on a regular grid of points.
"""
import numpy as np

CROSS_SECONDS = 12.0         # a tracer in the reference flux crosses the whole drawing in this many seconds of display time (the CFD: 12)
TRAIL = 7                    # points kept behind a tracer (the CFD: 7)
MAX_AGE = 14.0               # a tracer older than this starts again (the CFD: 14)
START_AGE = (0.0, 10.0)      # the ages the first tracers get (the CFD: 0 to 10)
RESTART_AGE = (0.0, 3.0)     # the age of a tracer that starts again (the CFD: 0 to 3)
MAX_RATIO = 4.0              # the speed ratio flux / reference flux stops here (a tracer must not jump across the drawing at a sharp corner)
INLET_BLEND = 0.1            # a tracer that starts again at an edge is put this far (of the way) from the edge to the middle of its triangle
SEED_BLEND = 0.02            # the same for the seeds of inlet_seeds (fixed lines): a smaller step, so that evenly spaced seeds stay evenly spaced
NO_FLOW = 1e-3               # a flux below this fraction of the reference flux is "no heat flow" (no arrow, no motion)
CANDIDATES = 16              # triangles tried (nearest centres first) when looking for the one that holds a point


def reference_flux(qmag):
    """The flux that counts as 'strong' in a picture: the 95th percentile of the flux of its triangles (0 when nothing flows)."""
    qmag = np.asarray(qmag, float)
    if qmag.size == 0:
        return 0.0
    ref = float(np.percentile(qmag, 95))
    return ref if ref > 0 else float(qmag.max())


class FluxField:
    """The drawing triangles with one heat-flux vector each; finds the triangle of a point.  `nodes` (n, 2) and `tris` (m, 3) are the drawing mesh."""

    def __init__(self, nodes, tris):
        from scipy.spatial import cKDTree
        nodes = np.asarray(nodes, float)[:, :2]
        tris = np.asarray(tris, dtype=np.int64)
        v = nodes[tris]                                        # (m, 3, 2)
        self.v = v
        self.x1, self.y1 = v[:, 0, 0], v[:, 0, 1]
        self.x2, self.y2 = v[:, 1, 0], v[:, 1, 1]
        self.x3, self.y3 = v[:, 2, 0], v[:, 2, 1]
        det = (self.y2 - self.y3) * (self.x1 - self.x3) + (self.x3 - self.x2) * (self.y1 - self.y3)
        self.good = np.abs(det) > 1e-300                       # a triangle without area holds nothing
        self.det = np.where(self.good, det, 1.0)
        self.area = 0.5 * np.abs(det)
        self.tree = cKDTree(v.mean(axis=1))
        pts = v.reshape(-1, 2)
        self.lo, self.hi = pts.min(axis=0), pts.max(axis=0)
        self.size = float(max(self.hi[0] - self.lo[0], self.hi[1] - self.lo[1]))
        self.qx, self.qy = np.zeros(len(v)), np.zeros(len(v))       # no flux until set_flux
        self.qref = 0.0
        self._boundary_edges(tris)
        self._inlet_w = np.zeros(len(self.b_len))

    def _boundary_edges(self, tris):
        """The edges that belong to one triangle only (the outline and the holes): the triangle, the end points, the length and the inward unit normal."""
        m = len(tris)
        pairs = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        owner = np.tile(np.arange(m), 3)
        key = np.sort(pairs, axis=1)
        _, first, inv, cnt = np.unique(key, axis=0, return_index=True, return_inverse=True, return_counts=True)
        only = cnt[inv.reshape(-1)] == 1
        own = owner[only]
        a = self.v_nodes_of(pairs[only, 0], tris, own)
        b = self.v_nodes_of(pairs[only, 1], tris, own)
        d = b - a
        L = np.hypot(d[:, 0], d[:, 1])
        n = np.stack([-d[:, 1], d[:, 0]], axis=1) / np.where(L > 0, L, 1.0)[:, None]
        mid = 0.5 * (a + b)
        cen = self.v[own].mean(axis=1)
        flip = np.sum(n * (cen - mid), axis=1) < 0
        n[flip] = -n[flip]
        self.b_tri, self.b_a, self.b_b, self.b_len, self.b_n, self.b_cen = own, a, b, L, n, cen

    def v_nodes_of(self, node_ids, tris, own):
        """The coordinates of node `node_ids[i]` of triangle `own[i]`."""
        k = np.argmax(tris[own] == np.asarray(node_ids)[:, None], axis=1)
        return self.v[own, k]

    def set_flux(self, qx, qy, qref=None):
        """The heat flux of every triangle (any unit, the same for all).  `qref` is the reference flux (default: reference_flux of this picture)."""
        qx, qy = np.asarray(qx, float).reshape(-1), np.asarray(qy, float).reshape(-1)
        if len(qx) != len(self.v) or len(qy) != len(self.v):
            raise ValueError("one heat-flux vector for every drawing triangle is needed")
        self.qx, self.qy = qx, qy
        self.qref = reference_flux(np.hypot(qx, qy)) if qref is None else float(qref)
        inflow = qx[self.b_tri] * self.b_n[:, 0] + qy[self.b_tri] * self.b_n[:, 1]        # the flux into the body through each outline edge
        self._inlet_w = np.where(inflow > NO_FLOW * self.qref, inflow, 0.0) * self.b_len if self.qref > 0 else np.zeros(len(self.b_len))

    def locate(self, pts):
        """The triangle that holds each point (-1: none).  `pts` (n, 2)."""
        pts = np.asarray(pts, float).reshape(-1, 2)
        n = len(pts)
        if n == 0:
            return np.zeros(0, dtype=np.int64)
        k = min(CANDIDATES, len(self.v))
        _, cand = self.tree.query(pts, k=k)
        cand = np.asarray(cand).reshape(n, -1)
        px, py = pts[:, 0:1], pts[:, 1:2]
        x3, y3 = self.x3[cand], self.y3[cand]
        d = self.det[cand]
        l1 = ((self.y2[cand] - y3) * (px - x3) + (x3 - self.x2[cand]) * (py - y3)) / d
        l2 = ((y3 - self.y1[cand]) * (px - x3) + (self.x1[cand] - x3) * (py - y3)) / d
        l3 = 1.0 - l1 - l2
        ok = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9) & self.good[cand]
        first = ok.argmax(axis=1)
        rows = np.arange(n)
        return np.where(ok[rows, first], cand[rows, first], -1)

    def flux_at(self, pts):
        """-> (q (n, 2), inside (n,) bool): the heat flux vector of the triangle that holds each point."""
        elem = self.locate(pts)
        inside = elem >= 0
        q = np.zeros((len(elem), 2))
        if np.any(inside):
            q[inside, 0] = self.qx[elem[inside]]
            q[inside, 1] = self.qy[elem[inside]]
        return q, inside

    def direction(self, pts):
        """-> (unit direction (n, 2) times the speed ratio, inside (n,)): where the heat goes at each point and how strongly: the flux over the reference
        flux (as the CFD: speed over free-stream speed), at most MAX_RATIO; no motion where the flux is below NO_FLOW of the reference."""
        q, inside = self.flux_at(pts)
        mag = np.hypot(q[:, 0], q[:, 1])
        out = np.zeros_like(q)
        if self.qref > 0:
            move = inside & (mag > NO_FLOW * self.qref)
            ratio = np.minimum(MAX_RATIO, mag[move] / self.qref)
            out[move] = q[move] / mag[move][:, None] * ratio[:, None]
        return out, inside

    def inlet_points(self, n, rng):
        """n points where heat enters the body: on the outline edges with the flux pointing in, chosen in proportion to the heat entering (length times
        flux), a little way in.  Without such an edge (heat made inside, or no heat), anywhere in the drawing."""
        tot = float(self._inlet_w.sum())
        if n == 0 or tot <= 0:
            return self.random_points(n, rng)
        e = rng.choice(len(self._inlet_w), size=n, p=self._inlet_w / tot)
        t = rng.random(n)[:, None]
        on_edge = self.b_a[e] + t * (self.b_b[e] - self.b_a[e])
        return (1.0 - INLET_BLEND) * on_edge + INLET_BLEND * self.b_cen[e]

    def inlet_seeds(self, n):
        """n points where heat enters the body, placed so that each one stands for the same share of the heat that enters (the heat entering through an edge is its length times
        its inward flux; the points are spaced evenly along the running total, in the order of the edges), a little way in.  The same every time.  None when no heat enters
        through an edge (heat made inside, or no heat): the caller then chooses where to start."""
        tot = float(self._inlet_w.sum())
        if n <= 0 or tot <= 0:
            return None
        cw = np.cumsum(self._inlet_w) / tot
        u = (np.arange(n) + 0.5) / n
        e = np.minimum(np.searchsorted(cw, u, side="right"), len(cw) - 1)
        before = np.where(e > 0, cw[np.maximum(e - 1, 0)], 0.0)
        t = np.clip((u - before) / np.maximum(cw[e] - before, 1e-300), 0.0, 1.0)[:, None]
        on_edge = self.b_a[e] + t * (self.b_b[e] - self.b_a[e])
        return (1.0 - SEED_BLEND) * on_edge + SEED_BLEND * self.b_cen[e]

    def random_points(self, n, rng):
        """n points spread evenly over the area of the drawing."""
        idx = rng.choice(len(self.v), size=n, p=self.area / self.area.sum())
        s = np.sqrt(rng.random(n))
        l2 = s * (1.0 - rng.random(n))
        l3 = s - l2                                            # l1 = 1 - s, l2 + l3 = s
        l1 = 1.0 - s
        v = self.v[idx]
        return l1[:, None] * v[:, 0] + l2[:, None] * v[:, 1] + l3[:, None] * v[:, 2]


class Tracers:
    """Small particles with a short trail, carried along the heat flux of a FluxField, as the tracers of the 2D CFD.  A tracer that leaves the drawing, or
    gets older than MAX_AGE, starts again where heat enters, so there are always `n` of them."""

    def __init__(self, field, n=700, seed=1):
        self.field = field
        self.n = int(n)
        self.rng = np.random.default_rng(seed)
        self.reseed()

    def reseed(self):
        self.p = self.field.random_points(self.n, self.rng)
        self.age = self.rng.uniform(START_AGE[0], START_AGE[1], self.n)
        self.trail = [[tuple(q)] for q in self.p]

    def step(self, dt=0.03):
        """Moves every tracer on by dt seconds of display time (midpoint rule)."""
        f = self.field
        h = f.size / CROSS_SECONDS * dt
        p = self.p
        v1, in1 = f.direction(p)
        v2, in2 = f.direction(p + 0.5 * h * v1)
        new = p + h * v2
        in3 = f.locate(new) >= 0
        self.age = self.age + dt
        dead = ~(in1 & in2 & in3) | (self.age > MAX_AGE)
        if np.any(dead):
            m = int(dead.sum())
            new[dead] = f.inlet_points(m, self.rng)
            self.age[dead] = self.rng.uniform(RESTART_AGE[0], RESTART_AGE[1], m)
        for i in range(len(new)):
            if dead[i]:
                self.trail[i] = [tuple(new[i])]
            else:
                self.trail[i].append(tuple(new[i]))
                if len(self.trail[i]) > TRAIL:
                    self.trail[i].pop(0)
        self.p = new


def arrow_samples(field, across=24):
    """The arrows of a picture: -> (points (k, 2), unit directions (k, 2), strength (k,) 0..1, spacing).  Points of a regular grid (about `across` of
    them over the longer side) that lie in the drawing and where heat flows."""
    step = field.size / max(1, int(across))
    xs = np.arange(field.lo[0] + step / 2, field.hi[0], step)
    ys = np.arange(field.lo[1] + step / 2, field.hi[1], step)
    gx, gy = np.meshgrid(xs, ys)
    pts = np.stack([gx.reshape(-1), gy.reshape(-1)], axis=1)
    q, inside = field.flux_at(pts)
    mag = np.hypot(q[:, 0], q[:, 1])
    keep = inside & (field.qref > 0) & (mag > NO_FLOW * field.qref)
    d = q[keep] / mag[keep][:, None]
    strength = np.minimum(1.0, mag[keep] / field.qref) if field.qref > 0 else np.zeros(0)
    return pts[keep], d, np.sqrt(strength), step
