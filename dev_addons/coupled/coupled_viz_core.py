"""coupled_viz_core.py - the numbers behind the Viz tab of the Coupled Physics window.  No Qt: it takes the results of the analyses of the LAST coupled solve (the fluid result, the stress
result) and makes what the picture is drawn from: the air temperature (or pressure) on the air mesh, the displacement (or von Mises stress) on the body mesh, the tracer lines (streamlines
from the velocity of the last pass), the particles that travel along them, the bent outline of the body, and the frame numbers of the animation.  A test can look at every one of them.

Nothing is solved here and nothing is written back: the picture shows what the solve gave.  Units: lengths are in the units of the sketch (the displacement is converted to mm), the air
temperature is shown in degC, the pressure in Pa.

The animation: 120 frames at 24 frames per second (5 s).  The result is steady, so only two things move: the body bends from nothing to its final shape (smooth ease over the first half, then it
stays), and the particles go along their tracer lines, once round in the whole animation (each from where it starts to where it started: the last frame is the first one with the body bent,
so the loop is seamless for the air).  The last frame is the still picture.  How fast the particles go on the screen is not how fast the air goes."""
import numpy as np

DEFAULTS = {"lines": 31, "per_line": 3, "trail": 6.0, "exaggeration": 30.0, "frames": 120, "fps": 24, "step": 0.5, "max_steps": 900, "seed": 3, "outline_points": 40, "tail_points": 12}
SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)
# the layers of the picture: key, name, the group that shows one at a time (the air, the body) or None
LAYERS = (("air_T", "Air temperature", "air"), ("tracers", "Tracers", None), ("body_u", "Body displacement", "body"), ("bent", "Bent outline (exaggerated)", None),
          ("air_p", "Air pressure", "air"), ("body_vm", "Von Mises stress", "body"))
LAYERS_ON = {"air_T": True, "tracers": True, "body_u": True, "bent": True, "air_p": False, "body_vm": False}
# the layers of the picture of a 2D heat and stress solve with no flow: the body shows one field at a time (temperature, displacement or von Mises stress)
LAYERS_HEAT = (("body_T", "Temperature", "body"), ("tracers", "Heat-flux tracers", None), ("body_u", "Body displacement", "body"), ("bent", "Bent outline (exaggerated)", None),
               ("body_vm", "Von Mises stress", "body"))
LAYERS_HEAT_ON = {"body_T": True, "tracers": True, "body_u": False, "bent": True, "body_vm": False}
HEAT_DEFAULTS = {"lines": 40, "per_line": 3, "trail_frac": 0.12, "margin": 0.08, "step_frac": 1.0 / 300.0, "max_steps": 1500, "ratio_min": 0.1, "max_laps": 8}
STOPS = {"inferno": [(0.0, "#000004"), (0.25, "#57106e"), (0.5, "#bc3754"), (0.75, "#f98e09"), (1.0, "#fcffa4")],
         "viridis": [(0.0, "#440154"), (0.25, "#3b528b"), (0.5, "#21918c"), (0.75, "#5ec962"), (1.0, "#fde725")]}
_LUT = {}


def set_layer(layers, key, on):
    """Switches a layer on or off; the layers of one group (the air: temperature or pressure; the body: displacement or von Mises) are shown one at a time, so switching one on
    switches the other off.  -> the new layers (a copy)."""
    out = dict(layers)
    group = {k: g for k, _n, g in LAYERS + LAYERS_HEAT}
    if key not in group:
        raise KeyError(key)
    out[key] = bool(on)
    if on and group[key] is not None:
        for k, g in group.items():
            if g == group[key] and k != key and k in out:
                out[k] = False
    return out


# ------------------------------------------------------------------------------------------------------------------------------ colours
def lut(name):
    """256 colours (uint8, 256 x 3) of a colour map ('inferno', 'viridis'), by linear steps between the key colours."""
    if name not in _LUT:
        stops = STOPS[name]
        pos = np.array([s for s, _c in stops])
        rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _s, c in stops], float)
        t = np.linspace(0, 1, 256)
        _LUT[name] = np.stack([np.interp(t, pos, rgb[:, j]) for j in range(3)], axis=1).round().astype(np.uint8)
    return _LUT[name]


def colours(values, lo, hi, name):
    """(n, 3) uint8 colours of the values between lo and hi (outside them: the end colours)."""
    v = np.asarray(values, float)
    t = np.zeros_like(v) if hi <= lo else np.clip((v - lo) / (hi - lo), 0.0, 1.0)
    return lut(name)[np.round(t * 255).astype(int)]


class Fit:
    """The window of the picture (x0, x1, y0, y1 in the units of the sketch) on a picture of w x h pixels: equal scale, centred, y up."""

    def __init__(self, view, w, h):
        x0, x1, y0, y1 = view
        self.view, self.w, self.h = view, int(w), int(h)
        self.s = min(w / (x1 - x0), h / (y1 - y0))
        self.ox = (w - self.s * (x1 - x0)) / 2.0 - self.s * x0
        self.oy = (h + self.s * (y1 - y0)) / 2.0 + self.s * y0

    def px(self, xy):
        a = np.asarray(xy, float)
        return np.stack([a[..., 0] * self.s + self.ox, self.oy - a[..., 1] * self.s], axis=-1)

    def world(self, pxy):
        a = np.asarray(pxy, float)
        return np.stack([(a[..., 0] - self.ox) / self.s, (self.oy - a[..., 1]) / self.s], axis=-1)


def raster(xy, tris, vals, fit, lo, hi, name):
    """The triangles of a mesh filled with colours: vals per node (smooth, Gouraud) or per triangle (flat).  -> (h, w, 4) uint8 (RGBA; transparent where there is no triangle)."""
    img = np.zeros((fit.h, fit.w, 4), np.uint8)
    P = fit.px(np.asarray(xy, float))
    tris = np.asarray(tris, int)
    vals = np.asarray(vals, float)
    flat = len(vals) == len(tris) and len(vals) != len(P)
    table = lut(name)
    span = (hi - lo) if hi > lo else 1.0
    for e, t in enumerate(tris):
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        xmin, xmax = int(max(0, np.floor(min(a[0], b[0], c[0])))), int(min(fit.w - 1, np.ceil(max(a[0], b[0], c[0]))))
        ymin, ymax = int(max(0, np.floor(min(a[1], b[1], c[1])))), int(min(fit.h - 1, np.ceil(max(a[1], b[1], c[1]))))
        if xmax < xmin or ymax < ymin:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / det
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / det
        l3 = 1.0 - l1 - l2
        eps = 1e-6
        inside = (l1 >= -eps) & (l2 >= -eps) & (l3 >= -eps)
        if not inside.any():
            continue
        v = np.full(gx.shape, vals[e]) if flat else l1 * vals[t[0]] + l2 * vals[t[1]] + l3 * vals[t[2]]
        idx = np.clip(np.round((v - lo) / span * 255), 0, 255).astype(int)
        block = img[ymin:ymax + 1, xmin:xmax + 1]
        block[inside, :3] = table[idx][inside]
        block[inside, 3] = 255
    return img


# ------------------------------------------------------------------------------------------------------------------------------ the animation
def ease(t):
    """Smooth step: 0 -> 1 (zero slope at both ends)."""
    t = min(1.0, max(0.0, float(t)))
    return t * t * (3.0 - 2.0 * t)


def bend_at(k, n=None):
    """How far the body has bent in frame k (1 .. n): 0 -> 1 over the first half with a smooth ease, then 1.  Frame 0 (before the first) is 0."""
    n = int(n or DEFAULTS["frames"])
    return ease(k / (n / 2.0))


def frame_delay_ms(fps=None, speed=1.0):
    return 1000.0 / (float(fps or DEFAULTS["fps"]) * float(speed))


class Player:
    """The frame counter of the playback bar (no timer: the page calls advance() with the time that passed).  Frames are 1 .. n; the still picture is frame n."""

    def __init__(self, n=None, fps=None):
        self.n = int(n or DEFAULTS["frames"])
        self.fps = float(fps or DEFAULTS["fps"])
        self.frame = self.n
        self.speed = 1.0
        self.loop = True
        self.playing = False
        self._acc = 0.0

    def play(self):
        if self.frame >= self.n and not self.loop:
            self.frame = 1
        self.playing = True
        self._acc = 0.0

    def pause(self):
        self.playing = False

    def seek(self, k):
        self.frame = min(self.n, max(1, int(k)))

    def advance(self, seconds):
        """The time `seconds` passed: moves on by the frames that fit (at fps x speed).  -> True when the frame changed.  Without Loop it stops at the last frame."""
        if not self.playing:
            return False
        self._acc += float(seconds) * self.fps * self.speed
        k = int(self._acc)
        if k <= 0:
            return False
        self._acc -= k
        old = self.frame
        self.frame += k
        if self.frame > self.n:
            if self.loop:
                self.frame = (self.frame - 1) % self.n + 1
            else:
                self.frame = self.n
                self.playing = False
        return self.frame != old


# ------------------------------------------------------------------------------------------------------------------------------ the data of a solve
def view_window(body_box, domain_box=None):
    """The part of the plane the picture shows, round the body: one body size to the left, four to the right, one and three quarters above and below (-20 .. 100 mm by -35 .. 55 mm for
    a 20 mm body at the origin), cut to the box of the air when that is smaller."""
    x0, y0, x1, y1 = (float(v) for v in body_box)
    S = max(x1 - x0, y1 - y0)
    win = [x0 - 1.0 * S, x1 + 4.0 * S, y0 - 1.75 * S, y1 + 1.75 * S]
    if domain_box is not None:
        a0, b0, a1, b1 = (float(v) for v in domain_box)
        win = [max(win[0], a0), min(win[1], a1), max(win[2], b0), min(win[3], b1)]
    return tuple(win)


def air_layer(flow):
    """The air from a fluid result: {"xy", "tris" (corners), "T" (degC, or None), "T_range", "p" (Pa at the corner nodes, or None), "p_range"}."""
    xy = np.asarray(flow["xy_sketch"], float)
    tris = np.asarray(flow["tri6"], int)[:, :3]
    out = {"xy": xy, "tris": tris, "T": None, "T_range": None, "p": None, "p_range": None}
    heat = flow.get("heat")
    if heat is not None and heat.get("T") is not None:
        T = np.asarray(heat["T"], float) - 273.15
        out["T"], out["T_range"] = T, (float(T.min()), float(T.max()))
    if flow.get("p") is not None:
        p = np.asarray(flow["p"], float)
        out["p"], out["p_range"] = p, (float(p.min()), float(p.max()))
    return out


def body_layer(body, length_per_unit=1.0):
    """The body from a stress result: {"xy" (nodes), "tris", "u" (n, 2) in mm, "umag" (mm), "u_range", "vm" (per triangle), "vm_range"}.  `length_per_unit`: mm per unit of the sketch."""
    m = body["mesh"]
    xy = np.asarray(m["nodes"], float)
    tris = np.asarray(m["tris"], int)
    u = np.asarray(body["u"], float) * float(length_per_unit)
    mag = np.hypot(u[:, 0], u[:, 1])
    out = {"xy": xy, "tris": tris, "u": u, "umag": mag, "u_range": (0.0, float(mag.max()) if len(mag) else 0.0), "vm": None, "vm_range": None}
    vm = body.get("vm")
    if vm is not None and len(vm) == len(tris):
        vm = np.asarray(vm, float)
        out["vm"], out["vm_range"] = vm, (float(vm.min()), float(vm.max()))
    return out


def tracer_lines(velocity, ys, x_start, x_end, step=None, max_steps=None):
    """Streamlines of a steady velocity field: one line from each of the points (x_start, y) of `ys`, followed in steps of `step` along the unit velocity (midpoint rule), until it leaves the
    mesh, the speed is nothing, it passes x_end, or after max_steps.  velocity(points (n, 2)) -> (vel (n, 2), inside (n,) bool).  Lines of fewer than 5 points are dropped.  -> [(n, 2) array]."""
    step = float(step or DEFAULTS["step"])
    max_steps = int(max_steps or DEFAULTS["max_steps"])
    ys = np.asarray(ys, float)
    pts = np.column_stack([np.full(len(ys), float(x_start)), ys])
    return _follow(velocity, pts, step, max_steps, x_end)


def _follow(velocity, pts, step, max_steps, x_end=None, drop=True):
    """The steps of tracer_lines, from any starting points (n, 2); with x_end a line also stops when it passes that x.  -> [(n, 2) array] (lines of fewer than 5 points dropped, unless
    drop is False: then there is one line for every starting point, in their order)."""
    lines = [[p.copy()] for p in pts]
    alive = np.arange(len(pts))
    cur = np.array(pts, float)
    for _ in range(max_steps):
        if not len(alive):
            break
        v1, in1 = velocity(cur[alive])
        for i in alive[~in1]:                                   # (the last step ended outside the mesh, in the body: that point is not part of the line)
            if len(lines[i]) > 1:
                lines[i].pop()
        sp = _norm(v1)
        ok = in1 & (sp > 1e-9)
        a = alive[ok]
        if not len(a):
            break
        mid = cur[a] + 0.5 * step * (v1[ok] / sp[ok][:, None])
        v2, in2 = velocity(mid)
        sp2 = _norm(v2)
        good = in2 & (sp2 > 1e-9)
        g = a[good]
        if not len(g):
            break
        new = cur[g] + step * (v2[good] / sp2[good][:, None])
        cur[g] = new
        for i, q in zip(g, new):
            lines[i].append(q.copy())
        alive = g if x_end is None else g[new[:, 0] < x_end]
    return [np.array(ln) for ln in lines if len(ln) >= 5] if drop else [np.array(ln) for ln in lines]


def _norm(v):
    """The lengths of the rows of v (n, 2) or (n, 3)."""
    v = np.asarray(v, float)
    return np.hypot(v[:, 0], v[:, 1]) if v.shape[1] == 2 else np.sqrt((v * v).sum(axis=1))


def arc_lengths(line):
    d = _norm(np.diff(line, axis=0))
    return np.concatenate([[0.0], np.cumsum(d)])


def particle_starts(lengths, per_line=None, seed=None):
    """Where each particle starts on its line, as a distance along it: at 15, 45 and 75 % of the line (for 3 per line), each moved by up to 12 % of the line (a fixed random series: the same
    every time).  -> [array (per_line,)]"""
    per_line = int(per_line or DEFAULTS["per_line"])
    rng = np.random.RandomState(DEFAULTS["seed"] if seed is None else seed)
    fr = np.array([(j + 0.5) / per_line for j in range(per_line)]) if per_line != 3 else np.array([0.15, 0.45, 0.75])
    return [np.clip(fr + rng.uniform(-0.12, 0.12, per_line), 0.0, 0.999) * L for L in lengths]


def outline_points(polys, kinds, n=None, hair=1e-4):
    """The outline of the body as drawn: every edge cut into n points (by length), moved by a hair toward the middle of the body so that they lie inside the mesh.  -> [(n, 2) array]"""
    n = int(n or DEFAULTS["outline_points"])
    cut = []
    for pts, kind in zip(polys, kinds):
        P = np.asarray(pts, float)
        if kind == "ci":
            P = np.vstack([P, P[:1]])
        c = arc_lengths(P)
        if c[-1] <= 0:
            continue
        s = np.linspace(0.0, c[-1], n)
        cut.append(np.stack([np.interp(s, c, P[:, 0]), np.interp(s, c, P[:, 1])], axis=1))
    if not cut:
        return []
    mid = np.vstack(cut).mean(axis=0)
    out = []
    for q in cut:
        d = mid - q
        L = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-300)[:, None]
        out.append(q + hair * d / L)
    return out


def build(flow, body, body_box, domain_box, polys, kinds, displacement_at, velocity, length_per_unit=1.0, options=None):
    """Everything the picture is drawn from.
    flow: the result of the fluid analysis; body: the result of the stress analysis; body_box / domain_box: (x0, y0, x1, y1) of the body and of the air; polys, kinds: the edges of the body
    (points, and 'ln' / 'ar' / 'ci'); displacement_at(points) -> (displacement (n, 2) in sketch units, gap); velocity(points) -> (vel, inside) of the air.  -> a dict (see the keys below)."""
    opt = dict(DEFAULTS)
    opt.update(options or {})
    win = view_window(body_box, domain_box)
    x0, y0, x1, y1 = (float(v) for v in body_box)
    S = max(x1 - x0, y1 - y0)
    ys = np.linspace(y0 - 1.3 * S, y1 + 1.3 * S, int(opt["lines"]))
    lines = tracer_lines(velocity, ys, x0 - 0.9 * S, x1 + 3.9 * S, opt["step"], opt["max_steps"])
    cums = [arc_lengths(ln) for ln in lines]
    lengths = [float(c[-1]) for c in cums]
    rest, disp = outline_and_displacement(polys, kinds, displacement_at, body, length_per_unit, opt)
    return {"window": win, "air": air_layer(flow), "body": body_layer(body, length_per_unit) if body is not None else None, "lines": lines, "cum": cums, "length": lengths,
            "starts": particle_starts(lengths, opt["per_line"], opt["seed"]), "rest": rest, "disp": disp, "length_per_unit": float(length_per_unit),
            "options": opt}


def outline_and_displacement(polys, kinds, displacement_at, body, length_per_unit, opt):
    """The outline of the body as drawn (outline_points) and the displacement of each of its points in mm (zero with no stress analysis: the body does not bend)."""
    rest = outline_points(polys, kinds, opt["outline_points"])
    disp = []
    for q in rest:
        U = displacement_at(q)[0] if (displacement_at is not None and body is not None) else np.zeros_like(q)
        disp.append(np.asarray(U, float) * float(length_per_unit))
    return rest, disp


# ------------------------------------------------------------------------------------------------------------------------------ the heat picture (2D, no flow)
# A 2D heat and stress solve with no flow has no air.  The picture is the body: coloured by its temperature, its displacement or its von Mises stress (one at a time), with tracer lines
# that follow the HEAT FLUX of the heat analysis (the last solve's final state), as the Heat flow of the 2D Thermal tab does (thermal_flow: the same FluxField), and the bent outline.
# The tracer lines are made like those of the flow, with the heat flux where the flow has the velocity: they start where heat enters the body, spaced so that every line stands for the
# same share of the heat that enters, and follow the flux until it leaves the body.  Particles travel along them; on a line a particle goes faster where the flux is stronger (its speed ratio
# is the flux over the strong flux of the picture, as in the Thermal tab) - a display, not a real speed.
HEAT_RATIO_MAX = 4.0                                                    # (the same as thermal_flow.MAX_RATIO: a particle never goes faster than this many times the reference speed)


def body_window(box, margin=None):
    """The part of the plane the heat picture shows: the box (x0, y0, x1, y1) of the body with a margin of 8 % of its longer side all round -> (x0, x1, y0, y1)."""
    x0, y0, x1, y1 = (float(v) for v in box)
    m = float(HEAT_DEFAULTS["margin"] if margin is None else margin) * max(x1 - x0, y1 - y0)
    return (x0 - m, x1 + m, y0 - m, y1 + m)


def reference_heat_flux(qmag, tmin, tmax):
    """The 'strong' heat flux of a result, which the speed of the particles is compared with: the 95th percentile of the flux of its triangles (the largest when that is 0), as the Heat flow of the
    2D Thermal tab takes it.  0 when nothing flows: no flux at all, or a temperature that is the same everywhere (a millionth of the temperature in kelvin is rounding noise)."""
    q = np.asarray(qmag, float)
    if q.size == 0 or float(tmax) - float(tmin) < 1e-6 * max(abs(float(tmax)), abs(float(tmin)), 1.0):
        return 0.0
    ref = float(np.percentile(q, 95))
    return ref if ref > 0 else float(q.max())


def heat_ratio(field, pts, ratio_min=None):
    """The speed ratio of heat at points: the heat flux over the strong flux of the picture (field.qref), held between ratio_min (0.1) and HEAT_RATIO_MAX.  0 where no flux is known (outside)."""
    lo = float(HEAT_DEFAULTS["ratio_min"] if ratio_min is None else ratio_min)
    q, inside = field.flux_at(pts)
    mag = _norm(q)
    r = np.clip(mag / field.qref, lo, HEAT_RATIO_MAX) if field.qref > 0 else np.full(len(mag), lo)
    return np.where(inside, r, 0.0)


def time_coordinate(line, ratios, ratio_min=None):
    """How far a particle has 'travelled' at each point of a line, counted in time: every step of the line is its length divided by the speed ratio there.  A particle that moves evenly in
    this coordinate goes `ratio` times as fast where the heat flux is `ratio` times the strong flux.  Units of length (a particle at ratio 1 covers one unit per unit); starts at 0."""
    lo = float(HEAT_DEFAULTS["ratio_min"] if ratio_min is None else ratio_min)
    ds = _norm(np.diff(line, axis=0))
    r = np.maximum(0.5 * (np.asarray(ratios, float)[:-1] + np.asarray(ratios, float)[1:]), lo)
    return np.concatenate([[0.0], np.cumsum(ds / r)])


def laps_for(periods, max_laps=None):
    """How many times the particles of each line go round it in the whole animation: the longest line (in time) once, a line that takes half as long twice, and so on (whole numbers, at
    most max_laps), so that the speeds along the different lines are about the same in time and every particle is back where it started at the last frame."""
    mx = float(HEAT_DEFAULTS["max_laps"] if max_laps is None else max_laps)
    top = max((float(p) for p in periods), default=0.0)
    return [int(min(mx, max(1, round(top / p)))) if p > 0 else 1 for p in periods]


def heat_lines(field, n, step=None, max_steps=None, seed=None):
    """The tracer lines of a heat flux: n lines from where heat enters the body (field.inlet_seeds), followed along the flux until it leaves the body or stops.  With no edge that heat enters
    through (heat made inside) the lines start at n points spread over the body and go both ways.  -> (lines [(n, 2) array], "edges" | "inside")."""
    step = float(step or field.size * HEAT_DEFAULTS["step_frac"])
    max_steps = int(max_steps or HEAT_DEFAULTS["max_steps"])
    seeds = field.inlet_seeds(int(n))
    if seeds is not None:
        return _follow(field.direction, seeds, step, max_steps), "edges"
    if field.qref <= 0 or int(n) <= 0:
        return [], "inside"
    pts = field.random_points(int(n), np.random.default_rng(DEFAULTS["seed"] if seed is None else seed))

    def back(P):
        v, inside = field.direction(P)
        return -v, inside
    fwd = _follow(field.direction, pts, step, max_steps, drop=False)
    bwd = _follow(back, pts, step, max_steps, drop=False)
    out = []
    for f, b in zip(fwd, bwd):
        ln = np.vstack([b[::-1][:-1], f]) if len(b) > 1 else f
        if len(ln) >= 5:
            out.append(ln)
    return out, "inside"


def thermal_layer(thermal, kelvin=273.15):
    """The temperature on the mesh of the heat analysis (degC): {"xy", "tris" (corners), "T", "T_range"}."""
    mesh = thermal["mesh"]
    T = np.asarray(thermal["T"], float) - float(kelvin)
    return {"xy": np.asarray(mesh["nodes"], float), "tris": np.asarray(mesh["tris"], int)[:, :3], "T": T, "T_range": (float(T.min()), float(T.max()))}


def build_heat(thermal, body, field, polys, kinds, displacement_at, length_per_unit=1.0, options=None):
    """Everything the picture of a 2D heat and stress solve with no flow is drawn from.
    thermal: the result of the heat analysis (T in kelvin on its mesh); body: the result of the stress analysis (or None); field: a thermal_flow.FluxField of the heat analysis with its heat
    flux set; polys, kinds: the edges of the body; displacement_at(points) -> (displacement (n, 2) in sketch units, gap).  -> a dict with "kind": "heat2d", the same keys as `build` gives for a
    flow where they mean the same (lines, cum, length, starts, rest, disp, window, body, options), "thermal" (the temperature layer) and "heat" (how the lines were made)."""
    opt = dict(DEFAULTS)
    opt.update(HEAT_DEFAULTS)
    opt.update(options or {})
    allp = np.vstack([np.asarray(p, float) for p in polys])
    box = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    lines, how = heat_lines(field, int(opt["lines"]), max_steps=opt["max_steps"])
    cums = [time_coordinate(ln, heat_ratio(field, ln, opt["ratio_min"]), opt["ratio_min"]) for ln in lines]
    lengths = [float(c[-1]) for c in cums]
    period = max(lengths, default=0.0)
    opt["trail"] = float(opt["trail_frac"]) * period
    rest, disp = outline_and_displacement(polys, kinds, displacement_at, body, length_per_unit, opt)
    return {"kind": "heat2d", "window": body_window(box, opt["margin"]), "air": {"xy": None, "tris": None, "T": None, "T_range": None, "p": None, "p_range": None},
            "thermal": thermal_layer(thermal), "body": body_layer(body, length_per_unit) if body is not None else None, "lines": lines, "cum": cums, "length": lengths,
            "starts": particle_starts(lengths, opt["per_line"], opt["seed"]), "laps": laps_for(lengths, opt["max_laps"]), "rest": rest, "disp": disp,
            "length_per_unit": float(length_per_unit), "options": opt, "heat": {"how": how, "qref": float(field.qref), "period": period, "wanted": int(opt["lines"])}}


def frame_state(data, k, exaggeration=None, n=None):
    """What moves in frame k (1 .. n): {"bend", "particles": [(x, y)], "tails": [[(x, y)] along the line, behind each particle], "outline": [(n, 2) arrays: the bent outline], "scale": the
    displacement of the body on the picture is `scale` x the real one (bend x exaggeration)}."""
    opt = data["options"]
    n = int(n or opt["frames"])
    ex = float(opt["exaggeration"] if exaggeration is None else exaggeration)
    bend = bend_at(k, n)
    parts, tails = [], []
    laps = data.get("laps")                                                     # (the heat picture: a short line is gone round more than once, so that every line is about as fast)
    for i, (line, cum, L, st) in enumerate(zip(data["lines"], data["cum"], data["length"], data["starts"])):
        lp = laps[i] if laps else 1
        for s0 in st:
            s = (s0 + lp * (k / n) * L) % L
            parts.append((float(np.interp(s, cum, line[:, 0])), float(np.interp(s, cum, line[:, 1]))))
            ss = np.clip(s - np.linspace(0.0, float(opt["trail"]), int(opt["tail_points"])), 0.0, None)
            tails.append(np.stack([np.interp(ss, cum, line[:, 0]), np.interp(ss, cum, line[:, 1])], axis=1))
    per_unit = data["length_per_unit"] or 1.0
    out = [q + bend * ex * d / per_unit for q, d in zip(data["rest"], data["disp"])]          # (the displacement was kept in mm: back to the units of the sketch)
    return {"bend": bend, "particles": parts, "tails": tails, "outline": out, "scale": bend * ex}


def particle_gap(data, ka, kb, n=None):
    """The largest distance (units of the sketch) that a particle is apart between frame ka and frame kb.  Between the last frame and frame 0 it is 0: every particle goes once round its line."""
    a = frame_state(data, ka, n=n)["particles"]
    b = frame_state(data, kb, n=n)["particles"]
    return max((float(np.hypot(p[0] - q[0], p[1] - q[1])) for p, q in zip(a, b)), default=0.0)


def bend_reach(data, k=None, n=None):
    """The largest displacement (mm, the real one: the exaggeration taken out again) of the points of the outline in frame k (the last one by default); 0 when the body has not bent yet."""
    opt = data["options"]
    n = int(n or opt["frames"])
    k = n if k is None else k
    st = frame_state(data, k, n=n)
    f = st["scale"]
    if f <= 0.0:
        return 0.0
    per_unit = data["length_per_unit"] or 1.0
    return max((float(np.hypot(*((o - q) * per_unit / f).T).max()) for o, q in zip(st["outline"], data["rest"]) if len(q)), default=0.0)


def effective_layers(data, layers):
    """The layers as they can be drawn for this solve: no air temperature without a heat exchange (the pressure is shown instead when the air is on), no body fields without a stress analysis."""
    out = dict(layers)
    a, b = data["air"], data["body"]
    if data.get("kind") == "heat2d":                                            # (no air here: the body shows its temperature, its displacement or its von Mises stress)
        out["air_T"] = out["air_p"] = False
        if b is None:
            out["body_u"] = out["body_vm"] = out["bent"] = False
        elif out.get("body_vm") and b["vm"] is None:
            out["body_vm"], out["body_u"] = False, True
        return out
    if out.get("air_T") and a["T"] is None:
        out["air_T"], out["air_p"] = False, a["p"] is not None
    if out.get("air_p") and a["p"] is None:
        out["air_p"] = False
    if b is None:
        out["body_u"] = out["body_vm"] = out["bent"] = False
    elif out.get("body_vm") and b["vm"] is None:
        out["body_vm"], out["body_u"] = False, True
    return out


def colour_bars(data, layers):
    """The colour bars the picture needs: [(title, lo, hi, colour map)] for the air field and the body field that are on."""
    bars = []
    a, b = data["air"], data["body"]
    lay = effective_layers(data, layers)
    if data.get("kind") == "heat2d":
        if lay.get("body_T"):
            bars.append(("Temperature (°C)", data["thermal"]["T_range"][0], data["thermal"]["T_range"][1], "inferno"))
        if lay.get("body_u"):
            bars.append(("Body displacement (mm)", b["u_range"][0], b["u_range"][1], "viridis"))
        elif lay.get("body_vm"):
            bars.append((f"Von Mises stress ({b.get('vm_unit', 'MPa')})", b["vm_range"][0], b["vm_range"][1], "viridis"))
        return bars
    if lay.get("air_T"):
        bars.append(("Air temperature (°C)", a["T_range"][0], a["T_range"][1], "inferno"))
    elif lay.get("air_p"):
        bars.append(("Air pressure (Pa)", a["p_range"][0], a["p_range"][1], "inferno"))
    if lay.get("body_u"):
        bars.append(("Body displacement (mm)", b["u_range"][0], b["u_range"][1], "viridis"))
    elif lay.get("body_vm"):
        bars.append(("Von Mises stress (MPa)", b["vm_range"][0], b["vm_range"][1], "viridis"))
    return bars


def ticks(lo, hi, title=""):
    """Where the colour bar is labelled: every 10 degC for a temperature, else the lowest, the middle and the highest value."""
    if "°C" in title and hi - lo >= 10:
        a = int(np.ceil(lo / 10.0)) * 10
        return [float(v) for v in range(a, int(np.floor(hi / 10.0)) * 10 + 1, 10)]
    return [float(lo), float((lo + hi) / 2.0), float(hi)]
