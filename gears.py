"""Involute gears, written from the standard gear formulas (no gear library).

Everything here is plain geometry:  module m, tooth count z, pressure angle a (the normal one for helical gears).
  pitch diameter  d  = m z                       base diameter  db = d cos(a)
  addendum        ha = m (1 + x)                 dedendum       hf = m (1.25 - x)        (x = profile shift)
  outside diameter da = d + 2 ha                 root diameter  df = d - 2 hf
A flank is the involute of the base circle: its polar angle at radius r is  inv(phi) = tan(phi) - phi  with  cos(phi) = rb / r.
The half-thickness (as an angle) of a tooth at radius r is  pi/(2z) + 2 x tan(a)/z + inv(a) - inv(phi_r) - backlash term.
"""
import math

from build123d import Axis, Circle, Edge, Face, Location, Plane, Polyline, Solid, Spline, Vector, Wire, extrude

GEAR_TYPES = ("Spur gear", "Helical gear", "Herringbone gear")


def inv(a):
    return math.tan(a) - a


def dims(p):
    """Every derived size of a gear from its main inputs, as a dict (angles in radians)."""
    z = int(round(p["teeth"]))
    if z < 3:
        raise ValueError("a gear needs at least 3 teeth")
    mn = float(p["module"])
    if mn <= 0:
        raise ValueError("the module must be positive")
    an = math.radians(float(p.get("pressure", 20)))
    beta = math.radians(float(p.get("helix", 0)))
    x = float(p.get("shift", 0))
    ha_f, hf_f = float(p.get("add", 1.0)), float(p.get("ded", 1.25))
    bl = float(p.get("backlash", 0))
    # the section the gear is cut in (perpendicular to its axis) has the transverse module and pressure angle
    mt = mn / math.cos(beta)
    at = math.atan(math.tan(an) / math.cos(beta))
    d = mt * z
    rp = d / 2
    rb = rp * math.cos(at)
    ra = rp + mn * (ha_f + x)
    rf = rp - mn * (hf_f - x)
    if rf <= 0 or ra <= rf:
        raise ValueError("these inputs leave no tooth: reduce the shift or the factors")
    return {"z": z, "mn": mn, "mt": mt, "an": an, "at": at, "beta": beta, "d": d, "rp": rp, "rb": rb, "ra": ra, "rf": rf,
            "da": 2 * ra, "df": 2 * rf, "db": 2 * rb, "x": x, "bl": bl,
            "pitch": math.pi * mt, "base_pitch": math.pi * mt * math.cos(at),
            "undercut": z < 2 * (ha_f - x) / math.sin(at) ** 2 * math.cos(beta) ** 3 if beta else z < 2 * (ha_f - x) / math.sin(an) ** 2}


def half_angle(D, r):
    """Half the angular thickness of a tooth at radius r (radians), measured from the tooth's centre line."""
    phi = math.acos(min(1.0, D["rb"] / r))
    ht = math.pi / (2 * D["z"]) + 2 * D["x"] * math.tan(D["at"]) / D["z"] + inv(D["at"]) - inv(phi)
    return ht - D["bl"] / (4 * D["rp"])           # backlash: take half of it off each flank, measured on the pitch circle


def polar(r, a):
    return (r * math.cos(a), r * math.sin(a))


def tooth_edges(D, n=24):
    """The edges of ONE tooth (centre line on the +X axis) from the root circle on its right to the root circle on its left:
    right flank, tip arc, left flank.  The root arc between teeth is added by the caller."""
    rb, ra, rf = D["rb"], D["ra"], D["rf"]
    r0 = max(rb, rf)                                     # the involute starts on the base circle, or on the root circle if that is bigger
    rs = [r0 + (ra - r0) * (i / n) ** 1.0 for i in range(n + 1)]
    right = [polar(r, -half_angle(D, r)) for r in rs]
    left = [polar(r, +half_angle(D, r)) for r in rs]
    from build123d import Line, ThreePointArc
    edges = []
    foot_r, foot_l = right[0], left[0]
    if rb > rf:                                          # below the base circle the flank runs straight in along the radius
        foot_r, foot_l = polar(rf, -half_angle(D, rb)), polar(rf, +half_angle(D, rb))
        edges.append(Line(Vector(*foot_r, 0), Vector(*right[0], 0)))
    edges.append(Spline(*[Vector(x, y, 0) for x, y in right]))
    ta = half_angle(D, ra)
    edges.append(ThreePointArc(Vector(*polar(ra, -ta), 0), Vector(ra, 0, 0), Vector(*polar(ra, ta), 0)))
    edges.append(Spline(*[Vector(x, y, 0) for x, y in reversed(left)]))
    if rb > rf:
        edges.append(Line(Vector(*left[0], 0), Vector(*foot_l, 0)))
    return edges, foot_r, foot_l


def profile_face(D):
    """The flat outline of the whole gear (z teeth) as a Face in the XY plane."""
    from build123d import ThreePointArc
    z, rf = D["z"], D["rf"]
    base, r_pt, l_pt = tooth_edges(D)
    pitch = 2 * math.pi / z
    edges = []
    for i in range(z):
        loc = Location((0, 0, 0), (0, 0, 1), math.degrees(i * pitch))
        edges += [e.moved(loc) for e in base]
        # root arc from this tooth's left foot to the next tooth's right foot
        a0 = math.atan2(l_pt[1], l_pt[0]) + i * pitch
        a1 = math.atan2(r_pt[1], r_pt[0]) + (i + 1) * pitch
        rr = math.hypot(*l_pt)
        mid = (a0 + a1) / 2
        edges.append(ThreePointArc(Vector(*polar(rr, a0), 0), Vector(*polar(rr, mid), 0), Vector(*polar(rr, a1), 0)))
    return Face(Wire(edges))


def spur_gear(p):
    """A spur gear as a Solid: axis = Z, from z = 0 up to the face width.  p: dict of numbers (see dims)."""
    D = dims({**p, "helix": 0})
    b = float(p["width"])
    if b <= 0:
        raise ValueError("the face width must be positive")
    body = extrude(profile_face(D), b)
    bore = float(p.get("bore", 0) or 0)
    if bore > 0:
        if bore >= 2 * D["rf"] - 1e-6:
            raise ValueError("the bore is as big as the root circle")
        body = body - extrude(Circle(bore / 2), b)
    return body


def twist_deg(D, length):
    """Turn (degrees, right-handed about +Z going up) of the tooth profile over an axial length so the teeth follow the helix angle."""
    return math.degrees(length * math.tan(D["beta"]) / D["rp"])


def finish(body, D, p, length):
    bore = float(p.get("bore", 0) or 0)
    if bore > 0:
        if bore >= 2 * D["rf"] - 1e-6:
            raise ValueError("the bore is as big as the root circle")
        body = body - extrude(Circle(bore / 2), length)
    return body


def helical_gear(p):
    """A helical gear: the spur outline (transverse section) turned steadily along the face width.  hand = 'right' or 'left'."""
    D = dims(p)
    b = float(p["width"])
    if b <= 0:
        raise ValueError("the face width must be positive")
    if D["beta"] == 0:
        return spur_gear(p)
    ang = twist_deg(D, b) * (1 if p.get("hand", "right") == "right" else -1)
    body = Solid.extrude_linear_with_rotation(profile_face(D), (0, 0, 0), (0, 0, b), ang)
    return finish(body, D, p, b)


def herringbone_gear(p):
    """Two opposite-hand helical halves meeting in the middle, with an optional groove (relief) of width p['groove'] between them."""
    D = dims(p)
    b, g = float(p["width"]), float(p.get("groove", 0) or 0)
    if D["beta"] == 0:
        raise ValueError("a herringbone gear needs a helix angle")
    h = (b - g) / 2
    if h <= 0:
        raise ValueError("the groove is as wide as the gear")
    sgn = 1 if p.get("hand", "right") == "right" else -1
    ang = twist_deg(D, h) * sgn
    face = profile_face(D)
    lower = Solid.extrude_linear_with_rotation(face, (0, 0, 0), (0, 0, h), ang)
    top_face = face.moved(Location((0, 0, h + g), (0, 0, 1), ang))
    upper = Solid.extrude_linear_with_rotation(top_face, (0, 0, h + g), (0, 0, h), -ang)
    if g > 0:
        core = extrude(Circle(D["rf"]).face().moved(Location((0, 0, h))), g)
        body = lower + core + upper
    else:
        body = lower + upper
    return finish(body, D, p, b)


def make(kind, p):
    """The solid for a gear type name (one of GEAR_TYPES) and a dict of numbers."""
    if kind == "Spur gear":
        return spur_gear(p)
    if kind == "Helical gear":
        return helical_gear(p)
    if kind == "Herringbone gear":
        return herringbone_gear(p)
    raise ValueError(f"unknown gear type {kind}")
