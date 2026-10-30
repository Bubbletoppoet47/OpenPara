"""
sk_dimlines.py - the drawing of a dimension in the sketch: extension lines, the dimension line with its arrows, a leader for a circle,
an arc for an angle.  Everything is worked out from the current geometry each time, so the lines always join what the dimension measures,
whatever a configuration does to the sketch.

shapes(ed, c) -> {"label": (u, v), "segs": [Nx2 arrays], "arrows": [[tip, back1, back2], ...]}  or None
    ed is the sketch editor (its model m, tag_base and the sketch size are used); c is a dimension constraint.

A dimension keeps where its label was put as c["off"] = [du, dv] (a distance from the label's automatic place, in mm) - used by the
length, radius and diameter dimensions - or as c["aoff"] = [f, k] for an angle: f = how far along its arc the label is (0 = on the first
line, 1 = on the second) and k = its distance from the corner as a multiple of the automatic distance.  An angle label can slide only
between its two lines, so it always stays inside the angle that was chosen.
"""
import math

import numpy as np

TAU = 2 * math.pi


def wrap_pi(a):
    return (a + math.pi) % TAU - math.pi


def extent(m):
    """Size of the sketch (the larger side of its box) - the scale for arrows and automatic distances."""
    pts = [p for i, p in m.pts.items()]
    if len(pts) < 2:
        return 10.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    e = max(max(xs) - min(xs), max(ys) - min(ys))
    return e if e > 1e-9 else 10.0


def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-12 else (1.0, 0.0)


def _arrow(tip, inward, size):
    """An open arrowhead: its tip, and the two back points; `inward` is the direction the arrow's body runs (away from the tip)."""
    ux, uy = inward
    nx, ny = -uy, ux
    return [tuple(np.add(tip, (ux * size + nx * size * 0.33, uy * size + ny * size * 0.33))), tuple(tip),
            tuple(np.add(tip, (ux * size - nx * size * 0.33, uy * size - ny * size * 0.33)))]


def angle_frame(ed, c):
    """(corner, a1, da, L0, e1len, e2len) of an angle dimension - the corner, the direction of the first side, the signed sweep to the
    second side, the automatic label distance and how far each line reaches along its side - or None (parallel lines)."""
    m = ed.m
    I = m.line_intersection(c["refs"])
    if I is None:
        return None
    m.ensure_angle(c)
    d1, d2 = m._dir(c["refs"][0][1]), m._dir(c["refs"][1][1])
    r1 = (c["s1"] * d1[0], c["s1"] * d1[1])
    r2 = (c["s2"] * d2[0], c["s2"] * d2[1])
    n1, n2 = math.hypot(*r1) or 1.0, math.hypot(*r2) or 1.0
    a1, a2 = math.atan2(r1[1], r1[0]), math.atan2(r2[1], r2[0])
    da = wrap_pi(a2 - a1)
    if abs(da) < 1e-9:
        return None
    reach = []
    for ref, a in ((c["refs"][0], a1), (c["refs"][1], a2)):
        p, q = m.line_pts(ref[1])
        e = (math.cos(a), math.sin(a))
        reach.append(max(0.0, max((p[0] - I[0]) * e[0] + (p[1] - I[1]) * e[1], (q[0] - I[0]) * e[0] + (q[1] - I[1]) * e[1])))
    return I, a1, da, 0.3 * (n1 + n2) / 2, reach[0], reach[1]


def angle_label(ed, c, fr=None):
    """(frac, rho) of an angle label: how far along the sector (0..1) and the distance from the corner."""
    if fr is None:
        fr = angle_frame(ed, c)
    I, a1, da, L0, _r1, _r2 = fr
    ao = c.get("aoff")
    if ao:
        return min(1.0, max(0.0, float(ao[0]))), max(0.05 * L0, float(ao[1]) * L0)
    off = c.get("off")
    if off:                                    # an older file: a free offset from the automatic place -> where that is, in polar terms
        b = (I[0] + L0 * math.cos(a1 + da / 2), I[1] + L0 * math.sin(a1 + da / 2))
        v = (b[0] + off[0] - I[0], b[1] + off[1] - I[1])
        th = math.atan2(v[1], v[0])
        f = wrap_pi(th - a1) / da
        return min(1.0, max(0.0, f)) if -0.5 <= f <= 1.5 else 0.5, max(0.05 * L0, math.hypot(*v))
    return 0.5, L0


def set_angle_label(ed, c, uv):
    """Move an angle's label to the plane point uv, held between the two sides of the angle."""
    fr = angle_frame(ed, c)
    if fr is None:
        return False
    I, a1, da, L0, _r1, _r2 = fr
    th = math.atan2(uv[1] - I[1], uv[0] - I[0])
    f = wrap_pi(th - a1) / da
    if f < 0 or f > 1:                         # outside the angle: it sticks to the nearer side
        d0 = abs(wrap_pi(th - a1))
        d1 = abs(wrap_pi(th - (a1 + da)))
        f = 0.0 if d0 < d1 else 1.0
    rho = max(0.05 * L0, math.hypot(uv[0] - I[0], uv[1] - I[1]))
    c["aoff"] = [round(f, 4), round(rho / L0, 4)]
    c.pop("off", None)
    return True


def centroid(m):
    pts = [p for i, p in m.pts.items() if i != 0] or list(m.pts.values())
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else (0.0, 0.0)


def shapes(ed, c):
    m, t = ed.m, c["type"]
    base = ed.tag_base(c)
    if base is None:
        return None
    ext = extent(m)
    s = 0.022 * ext                            # arrow size
    gap, over = 0.4 * s, 0.9 * s
    segs, arrows = [], []
    try:
        if t in ("dim_h", "dim_v", "dim_len"):
            A, B = m._two_points(c["refs"])
            if A is None:
                return {"label": base, "segs": [], "arrows": []}
            u = (1.0, 0.0) if t == "dim_h" else (0.0, 1.0) if t == "dim_v" else _unit((B[0] - A[0], B[1] - A[1]))
            n = (-u[1], u[0])
            off = c.get("off")
            if off:
                L = (base[0] + off[0], base[1] + off[1])
            else:                              # automatically a little outside the drawing, on the side away from its middle
                cx, cy = centroid(m)
                side = 1.0 if ((base[0] - cx) * n[0] + (base[1] - cy) * n[1]) >= -1e-12 else -1.0
                L = (base[0] + side * n[0] * 0.1 * ext, base[1] + side * n[1] * 0.1 * ext)
            dist = lambda P: (L[0] - P[0]) * n[0] + (L[1] - P[1]) * n[1]            # how far the dimension line is from P, across
            along = lambda P: P[0] * u[0] + P[1] * u[1]
            tA, tB, tL = along(A), along(B), along(L)
            perp0 = L[0] * n[0] + L[1] * n[1]
            pt = lambda tt: (u[0] * tt + n[0] * perp0, u[1] * tt + n[1] * perp0)
            lo, hi = min(tA, tB, tL), max(tA, tB, tL)
            segs.append(np.array([pt(lo), pt(hi)]))
            for P, tt in ((A, tA), (B, tB)):
                d = dist(P)
                if abs(d) > gap:
                    sg = 1.0 if d > 0 else -1.0
                    segs.append(np.array([(P[0] + n[0] * sg * gap, P[1] + n[1] * sg * gap), (pt(tt)[0] + n[0] * sg * over, pt(tt)[1] + n[1] * sg * over)]))
            lo_t, hi_t = min(tA, tB), max(tA, tB)
            if hi_t - lo_t > 2.2 * s:
                arrows.append(_arrow(pt(lo_t), u, s))
                arrows.append(_arrow(pt(hi_t), (-u[0], -u[1]), s))
            else:                              # too short for arrows between the lines: they point in from outside
                arrows.append(_arrow(pt(lo_t), (-u[0], -u[1]), s))
                arrows.append(_arrow(pt(hi_t), u, s))
                segs.append(np.array([pt(lo_t - 2.2 * s), pt(lo_t)]))
                segs.append(np.array([pt(hi_t), pt(hi_t + 2.2 * s)]))
            return {"label": L, "segs": segs, "arrows": arrows}
        if t in ("dim_rad", "dim_dia"):
            k, i = c["refs"][0]
            if k == "ci":
                C, r = m.pts[m.cis[i]["c"]], m.cis[i]["r"]
            else:
                C, r = m.pts[m.ars[i]["c"]], m.radius("ar", i)
            off = c.get("off")
            L = (base[0] + off[0], base[1] + off[1]) if off else base
            e = _unit((L[0] - C[0], L[1] - C[1]))
            P = (C[0] + e[0] * r, C[1] + e[1] * r)
            far = math.hypot(L[0] - C[0], L[1] - C[1]) > r
            if t == "dim_dia":
                Q = (C[0] - e[0] * r, C[1] - e[1] * r)
                segs.append(np.array([Q, L if far else P]))
                arrows.append(_arrow(Q, e, min(s, r * 0.8)))
            else:
                segs.append(np.array([C, L if far else P]))
            arrows.append(_arrow(P, (-e[0], -e[1]), min(s, r * 0.8)))
            return {"label": L, "segs": segs, "arrows": arrows}
        if t == "dim_ang":
            fr = angle_frame(ed, c)
            if fr is None:
                off = c.get("off")
                return {"label": (base[0] + off[0], base[1] + off[1]) if off else base, "segs": [], "arrows": []}
            I, a1, da, L0, reach1, reach2 = fr
            f, rho = angle_label(ed, c, fr)
            th = a1 + f * da
            L = (I[0] + rho * math.cos(th), I[1] + rho * math.sin(th))
            n = max(8, int(abs(da) / TAU * 96))
            arc = np.array([(I[0] + rho * math.cos(a1 + da * k / n), I[1] + rho * math.sin(a1 + da * k / n)) for k in range(n + 1)])
            segs.append(arc)
            sg = 1.0 if da > 0 else -1.0
            for a, reach in ((a1, reach1), (a1 + da, reach2)):
                e = (math.cos(a), math.sin(a))
                if reach < rho:                # the line stops short of the arc: an extension line takes over
                    lo = max(reach, 0.0) + gap
                    segs.append(np.array([(I[0] + e[0] * lo, I[1] + e[1] * lo), (I[0] + e[0] * (rho + over), I[1] + e[1] * (rho + over))]))
            sz = min(s, 0.25 * rho)
            for a, direction in ((a1, 1.0), (a1 + da, -1.0)):
                tip = (I[0] + rho * math.cos(a), I[1] + rho * math.sin(a))
                tang = (-math.sin(a) * sg * direction, math.cos(a) * sg * direction)        # along the arc, towards the middle of the angle
                arrows.append(_arrow(tip, tang, sz))
            return {"label": L, "segs": segs, "arrows": arrows}
    except Exception:
        return {"label": base, "segs": [], "arrows": []}
    return {"label": base, "segs": [], "arrows": []}
