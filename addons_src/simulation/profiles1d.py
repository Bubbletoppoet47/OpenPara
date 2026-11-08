"""Basic cross-sections for the 1D FEA (beam) tab.

A profile is a plain dict, stored inside each member:

    {"shape": key, "dims": {...}, "flip": bool, "weak": bool,
     "A": area, "I": second moment of area about the horizontal centroidal axis (the axis the member bends about),
     "c_top": distance from the centroid to the extreme fibre on the member's +y (left) side,
     "c_bottom": the same on the -y side, "label": short text}

All lengths are in the tab's length unit (the numbers are only ever combined consistently, so no unit is built in here).

"y" is the direction the member bends in (in the plane of the frame); "h" always means the depth in that direction.
Shapes built from polygons use section_props.properties (exact polygon integrals); round shapes use their closed forms.
"""
import math

import section_props as secp

# key, label, [(dimension key, label, default in millimetres)]
SHAPES = [
    ("rect", "Solid rectangle", [("b", "Width b (out of the frame plane)", 50.0), ("h", "Depth h (in the frame plane)", 100.0)]),
    ("round", "Solid round bar", [("d", "Diameter d", 50.0)]),
    ("pipe", "Round pipe / tube", [("d", "Outer diameter D", 60.3), ("t", "Wall thickness t", 3.9)]),
    ("rtube", "Rectangular / square tube", [("b", "Outer width b (out of the plane)", 50.0), ("h", "Outer depth h (in the plane)", 100.0),
                                            ("t", "Wall thickness t", 4.0)]),
    ("ibeam", "I / H beam", [("bf", "Flange width bf", 100.0), ("h", "Overall depth h", 200.0), ("tf", "Flange thickness tf", 8.0),
                             ("tw", "Web thickness tw", 5.6)]),
    ("channel", "Channel (web vertical)", [("bf", "Flange width bf", 75.0), ("h", "Overall depth h", 150.0), ("tf", "Flange thickness tf", 7.0),
                                           ("tw", "Web thickness tw", 5.0)]),
    ("tee", "T section (flange on top)", [("bf", "Flange width bf", 100.0), ("h", "Overall depth h", 100.0), ("tf", "Flange thickness tf", 8.0),
                                          ("tw", "Stem thickness tw", 8.0)]),
    ("angle", "Angle (L section)", [("b", "Horizontal leg b", 50.0), ("h", "Vertical leg h", 50.0), ("t", "Thickness t", 5.0)]),
    ("custom", "Enter A, I and c directly", [("A", "Area A", 1000.0), ("I", "Second moment of area I", 1.0e6),
                                              ("c_top", "Distance to top fibre c_top", 50.0), ("c_bottom", "Distance to bottom fibre c_bottom", 50.0)]),
]
SHAPE_KEYS = [s[0] for s in SHAPES]
_BY_KEY = {s[0]: s for s in SHAPES}


def shape_label(key):
    return _BY_KEY[key][1] if key in _BY_KEY else "Imported"


def dim_defs(key):
    return [(k, lab) for k, lab, _ in _BY_KEY[key][2]]


def default_dims(key, length_m):
    """Starting numbers for a shape, converted from millimetres to a length unit that is `length_m` metres long.
    The custom shape's A (mm2), I (mm4) and c (mm) are converted with the matching powers."""
    f = 1.0e-3 / length_m
    out = {}
    for k, _, v in _BY_KEY[key][2]:
        if key == "custom":
            pw = {"A": 2, "I": 4}.get(k, 1)
            out[k] = v * f ** pw
        else:
            out[k] = v * f
    return out


def _rect(w, h):
    return [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]


def _circle(r, n=72):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _faces(key, d):
    """The outline of the section as the face dicts section_props expects (outer polygon counter-clockwise, holes as 'holes')."""
    if key == "rect":
        return [{"poly": _rect(d["b"], d["h"]), "holes": []}]
    if key == "round":
        return [{"poly": _circle(d["d"] / 2), "holes": []}]
    if key == "pipe":
        return [{"poly": _circle(d["d"] / 2), "holes": [{"poly": _circle(d["d"] / 2 - d["t"])}]}]
    if key == "rtube":
        return [{"poly": _rect(d["b"], d["h"]), "holes": [{"poly": _rect(d["b"] - 2 * d["t"], d["h"] - 2 * d["t"])}]}]
    if key == "ibeam":
        bf, h, tf, tw = d["bf"], d["h"], d["tf"], d["tw"]
        pts = [(-bf / 2, -h / 2), (bf / 2, -h / 2), (bf / 2, -h / 2 + tf), (tw / 2, -h / 2 + tf), (tw / 2, h / 2 - tf), (bf / 2, h / 2 - tf),
               (bf / 2, h / 2), (-bf / 2, h / 2), (-bf / 2, h / 2 - tf), (-tw / 2, h / 2 - tf), (-tw / 2, -h / 2 + tf), (-bf / 2, -h / 2 + tf)]
        return [{"poly": pts, "holes": []}]
    if key == "channel":
        bf, h, tf, tw = d["bf"], d["h"], d["tf"], d["tw"]
        pts = [(0, 0), (bf, 0), (bf, tf), (tw, tf), (tw, h - tf), (bf, h - tf), (bf, h), (0, h)]
        return [{"poly": pts, "holes": []}]
    if key == "tee":
        bf, h, tf, tw = d["bf"], d["h"], d["tf"], d["tw"]
        pts = [(-tw / 2, 0), (tw / 2, 0), (tw / 2, h - tf), (bf / 2, h - tf), (bf / 2, h), (-bf / 2, h), (-bf / 2, h - tf), (-tw / 2, h - tf)]
        return [{"poly": pts, "holes": []}]
    if key == "angle":
        b, h, t = d["b"], d["h"], d["t"]
        return [{"poly": [(0, 0), (b, 0), (b, t), (t, t), (t, h), (0, h)], "holes": []}]
    raise ValueError(f"Unknown shape '{key}'.")


def _check(key, d):
    for k, v in d.items():
        if not (isinstance(v, (int, float)) and math.isfinite(v) and v > 0):
            raise ValueError(f"'{k}' must be a positive number.")
    if key == "pipe" and not d["t"] < d["d"] / 2:
        raise ValueError("The wall thickness must be less than half the outer diameter.")
    if key == "rtube" and not d["t"] < min(d["b"], d["h"]) / 2:
        raise ValueError("The wall thickness must be less than half of both outer sizes.")
    if key in ("ibeam", "channel") and not 2 * d["tf"] < d["h"]:
        raise ValueError("The two flanges are thicker than the whole depth.")
    if key == "tee" and not d["tf"] < d["h"]:
        raise ValueError("The flange is thicker than the whole depth.")
    if key in ("ibeam", "channel", "tee") and not d["tw"] < d["bf"]:
        raise ValueError("The web (stem) must be thinner than the flange is wide.")
    if key == "angle" and not (d["t"] < d["b"] and d["t"] < d["h"]):
        raise ValueError("The thickness must be smaller than both legs.")


def _fmt(v):
    return f"{v:.4g}"


def make_label(key, d):
    if key == "custom":
        return f"A={_fmt(d['A'])} I={_fmt(d['I'])}"
    nm = {"rect": "Rect", "round": "Round", "pipe": "Pipe", "rtube": "Tube", "ibeam": "I-beam", "channel": "Channel", "tee": "Tee",
          "angle": "Angle"}[key]
    order = [k for k, _, _ in _BY_KEY[key][2]]
    return nm + " " + " x ".join(_fmt(d[k]) for k in order)


def shear_area_of(key, d, weak=False):
    """Effective shear area As (for the shear deformation of the Timoshenko option): the web for I / channel / tee / tube sections, the usual
    factors for solid ones, half the area as a rough guess for an angle.  None for a section known only by numbers."""
    if key in ("custom", "imported"):
        return None
    if key == "rect":
        return 5.0 / 6.0 * d["b"] * d["h"]
    if key == "round":
        return 0.9 * math.pi * d["d"] ** 2 / 4
    if key == "pipe":
        return 0.5 * math.pi * (d["d"] ** 2 - (d["d"] - 2 * d["t"]) ** 2) / 4
    if key == "rtube":
        return 2.0 * d["t"] * (d["b"] if weak else d["h"])
    if key in ("ibeam", "channel"):
        return 2.0 * d["bf"] * d["tf"] if weak else d["tw"] * d["h"]
    if key == "tee":
        return d["bf"] * d["tf"] if weak else d["tw"] * d["h"]
    return None                                           # angle: handled by the caller (half the area)


def _rot90(poly):
    return [(-y, x) for x, y in poly]


def _outline(key, d, flip, weak):
    """[(polygon, is_hole)] of the base section as it is drawn (turned for the weak axis, flipped), y up."""
    faces = _faces(key, d)
    if weak and key not in ("round", "pipe"):
        faces = [{"poly": _rot90(f["poly"]), "holes": [{"poly": _rot90(h["poly"])} for h in f["holes"]]} for f in faces]
    out = []
    for f in faces:
        out.append((f["poly"], False))
        for h in f["holes"]:
            out.append((h["poly"], True))
    if flip:
        out = [([(x, -y) for x, y in poly], hole) for poly, hole in out]
    return out


def _base(key, d, flip, weak):
    """The section before any copies: A, I, As, fibre distances, the drawn outline, its box and the height of its centroid in the drawing."""
    yc0 = 0.0
    if key == "custom":
        A, I, ct, cb = d["A"], d["I"], d["c_top"], d["c_bottom"]
    elif key == "round":
        A, I, ct, cb = math.pi * d["d"] ** 2 / 4, math.pi * d["d"] ** 4 / 64, d["d"] / 2, d["d"] / 2
    elif key == "pipe":
        di = d["d"] - 2 * d["t"]
        A, I, ct, cb = math.pi * (d["d"] ** 2 - di ** 2) / 4, math.pi * (d["d"] ** 4 - di ** 4) / 64, d["d"] / 2, d["d"] / 2
    else:
        faces = _faces(key, d)
        if weak:                                           # turn the section 90 degrees: it then bends about its other axis
            faces = [{"poly": _rot90(f["poly"]), "holes": [{"poly": _rot90(h["poly"])} for h in f["holes"]]} for f in faces]
        pr = secp.properties(faces)
        A, I, ct, cb, yc0 = pr["area"], pr["Ixx"], pr["c_top"], pr["c_bottom"], pr["yc"]
    if flip:
        ct, cb, yc0 = cb, ct, -yc0
    polys = [] if key == "custom" else _outline(key, d, flip, weak)
    if polys:
        xs = [x for poly, _h in polys for x, _y in poly]
        ys = [y for poly, _h in polys for _x, y in poly]
        box = (min(xs), max(xs), min(ys), max(ys))
    else:
        box = (0.0, 0.0, yc0 - cb, yc0 + ct)
    As = shear_area_of(key, d, weak)
    if As is None and key == "angle":
        As = 0.5 * A
    return {"A": A, "I": I, "As": As, "ct": ct, "cb": cb, "polys": polys, "box": box, "yc0": yc0}


COPY_DEFAULTS = {"nx": 1, "gx": 0.0, "ny": 1, "gy": 0.0, "mirror_v": False, "gap_v": 0.0, "mirror_h": False, "gap_h": 0.0,
                 "side_v": "right", "side_h": "top"}
MAX_COPIES = 200


def normalize_copies(c):
    """The copies spec with every field present and checked.  Raises ValueError with a message for the user.  None / no copies -> None."""
    if not c:
        return None
    out = dict(COPY_DEFAULTS)
    out.update({k: c[k] for k in COPY_DEFAULTS if k in c})
    for k in ("nx", "ny"):
        out[k] = int(out[k])
        if not 1 <= out[k] <= 50:
            raise ValueError("A linear pattern needs a count from 1 to 50.")
    for k in ("gx", "gy", "gap_v", "gap_h"):
        v = float(out[k])
        if not (math.isfinite(v) and v >= 0):
            raise ValueError("A gap between copies must be 0 or more (copies cannot overlap).")
        out[k] = v
    out["mirror_v"], out["mirror_h"] = bool(out["mirror_v"]), bool(out["mirror_h"])
    if out["side_v"] not in ("right", "left") or out["side_h"] not in ("top", "bottom"):
        raise ValueError("The side of a mirror copy must be right or left (vertical axis), top or bottom (horizontal axis).")
    if copy_count(out) > MAX_COPIES:
        raise ValueError(f"That is {copy_count(out)} copies; the limit is {MAX_COPIES}.")
    return None if copy_count(out) == 1 else out


def copy_count(c):
    if not c:
        return 1
    return int(c.get("nx", 1)) * int(c.get("ny", 1)) * (2 if c.get("mirror_v") else 1) * (2 if c.get("mirror_h") else 1)


def _layout(box, c):
    """The copies as (sx, sy, tx, ty): a point (x, y) of the base goes to (sx x + tx, sy y + ty).  Linear patterns first (a gap is the clear
    distance between neighbouring boxes), then the mirrors; a mirror line sits half a gap beyond the pattern, so the gap is the space between."""
    x0, x1, y0, y1 = box
    w, h = x1 - x0, y1 - y0
    cps = [(1, 1, i * (w + c["gx"]), j * (h + c["gy"])) for i in range(c["nx"]) for j in range(c["ny"])]

    def ext(t):
        sx, sy, tx, ty = t
        xs = (sx * x0 + tx, sx * x1 + tx)
        ys = (sy * y0 + ty, sy * y1 + ty)
        return min(xs), max(xs), min(ys), max(ys)
    if c["mirror_v"]:
        xl = (max(ext(t)[1] for t in cps) + c["gap_v"] / 2 if c["side_v"] == "right"
              else min(ext(t)[0] for t in cps) - c["gap_v"] / 2)
        cps = cps + [(-sx, sy, 2 * xl - tx, ty) for sx, sy, tx, ty in cps]
    if c["mirror_h"]:
        yl = (max(ext(t)[3] for t in cps) + c["gap_h"] / 2 if c["side_h"] == "top"
              else min(ext(t)[2] for t in cps) - c["gap_h"] / 2)
        cps = cps + [(sx, -sy, tx, 2 * yl - ty) for sx, sy, tx, ty in cps]
    return cps, ext


def _combine(base, c):
    """A, I, As, c_top, c_bottom of all the copies taken as one section (parallel-axis theorem: copies above or below each other add A d^2)."""
    cps, ext = _layout(base["box"], c)
    A_i, I_i, As_i, yc_i, y_hi, y_lo = [], [], [], [], [], []
    for t in cps:
        _x0, _x1, lo, hi = ext(t)
        A_i.append(base["A"])
        I_i.append(base["I"])
        As_i.append(base["As"])
        yc_i.append(t[1] * base["yc0"] + t[3])
        y_hi.append(hi)
        y_lo.append(lo)
    A = sum(A_i)
    yc = sum(a * y for a, y in zip(A_i, yc_i)) / A
    I = sum(i + a * (y - yc) ** 2 for i, a, y in zip(I_i, A_i, yc_i))
    As = None if base["As"] is None else sum(As_i)
    return {"A": A, "I": I, "As": As, "ct": max(y_hi) - yc, "cb": yc - min(y_lo), "n": len(cps)}


def compute(key, dims, flip=False, weak=False, copies=None):
    """-> profile dict (see the module text).  Raises ValueError with a message for the user.
    copies: None, or the mirrors / linear patterns that make one member stand for several equal sections that deflect together
    (see COPY_DEFAULTS); the section is then the combined one."""
    if key not in _BY_KEY:
        raise ValueError(f"Unknown shape '{key}'.")
    d = {}
    for k, _, _ in _BY_KEY[key][2]:
        if k not in dims:
            raise ValueError(f"Missing dimension '{k}'.")
        d[k] = float(dims[k])
    _check(key, d)
    cp = normalize_copies(copies)
    base = _base(key, d, flip, weak)
    A, I, ct, cb, As = base["A"], base["I"], base["ct"], base["cb"], base["As"]
    n = 1
    if cp:
        comb = _combine(base, cp)
        A, I, ct, cb, As, n = comb["A"], comb["I"], comb["ct"], comb["cb"], comb["As"], comb["n"]
    if not (A > 0 and I > 0 and ct > 0 and cb > 0):
        raise ValueError("The section has no area, no stiffness, or a fibre distance of zero.")
    label = make_label(key, d) + (" (weak axis)" if weak and key not in ("round", "pipe", "custom") else "") + (" (flipped)" if flip else "")
    if cp:
        label += f" ({n} copies)"
    out = {"shape": key, "dims": d, "flip": bool(flip), "weak": bool(weak), "A": A, "I": I, "c_top": ct, "c_bottom": cb, "label": label}
    if As is not None:
        out["As"] = As
    if cp:
        out["copies"] = cp
    return out


def shear_area(profile):
    """As of a stored profile (older files do not have it: it is worked out again from the shape)."""
    if profile is None:
        return None
    if profile.get("As"):
        return float(profile["As"])
    if profile.get("shape") in (None, "custom", "imported"):
        return None
    try:
        return compute(profile["shape"], profile["dims"], profile.get("flip", False), profile.get("weak", False), profile.get("copies")).get("As")
    except ValueError:
        return None


def drawing(profile, n_circle=48):
    """Faces (outer polygon + holes) to draw the section, in the profile's own units, y up, as a list of polygons with a flag:
    [(polygon, is_hole)].  Every copy is drawn.  A section entered by numbers has no drawing (returns [])."""
    key = profile.get("shape")
    if key in (None, "custom", "imported"):
        return []
    d = profile["dims"]
    polys = _outline(key, d, bool(profile.get("flip")), bool(profile.get("weak")))
    cp = normalize_copies(profile.get("copies"))
    if not cp:
        return polys
    base = _base(key, d, bool(profile.get("flip")), bool(profile.get("weak")))
    cps, _ext = _layout(base["box"], cp)
    out = []
    for sx, sy, tx, ty in cps:
        for poly, hole in polys:
            out.append(([(sx * x + tx, sy * y + ty) for x, y in poly], hole))
    return out


def imported(name, A, I, c_top, c_bottom):
    """A profile that came from a .profprops file (numbers only)."""
    if not (A > 0 and I > 0 and c_top > 0 and c_bottom > 0):
        raise ValueError("The profile needs a positive area, moment of inertia and fibre distances.")
    return {"shape": "imported", "dims": {}, "flip": False, "weak": False, "A": A, "I": I, "c_top": c_top, "c_bottom": c_bottom,
            "label": name or f"A={_fmt(A)} I={_fmt(I)}"}


def scale(profile, lf):
    """The same profile with every length multiplied by lf (a change of length unit)."""
    p = dict(profile)
    p["dims"] = dict(profile.get("dims", {}))
    if profile.get("shape") == "custom":
        p["dims"] = {"A": p["dims"]["A"] * lf ** 2, "I": p["dims"]["I"] * lf ** 4, "c_top": p["dims"]["c_top"] * lf,
                     "c_bottom": p["dims"]["c_bottom"] * lf}
    else:
        p["dims"] = {k: v * lf for k, v in p["dims"].items()}
    p["A"] = profile["A"] * lf ** 2
    if profile.get("As"):
        p["As"] = profile["As"] * lf ** 2
    if profile.get("copies"):
        p["copies"] = dict(profile["copies"])
        for k in ("gx", "gy", "gap_v", "gap_h"):
            p["copies"][k] = p["copies"][k] * lf
    p["I"] = profile["I"] * lf ** 4
    p["c_top"] = profile["c_top"] * lf
    p["c_bottom"] = profile["c_bottom"] * lf
    return p


def with_dim(profile, key, value):
    """The profile with one dimension changed (used by the Parameterization tab).  Raises ValueError."""
    if profile.get("shape") in (None, "imported") or key not in profile.get("dims", {}):
        raise ValueError(f"This profile has no dimension '{key}'.")
    dims = dict(profile["dims"])
    dims[key] = float(value)
    return compute(profile["shape"], dims, profile.get("flip", False), profile.get("weak", False), profile.get("copies"))


def fibres(profile, nf=60):
    """The section cut into horizontal strips for the nonlinear solver: (y, dA) arrays, y measured from the centroid (+ toward the member's +y side),
    dA scaled so that the strips add up to the exact area.  Strips follow the corners of the outline.  None for a section known only by numbers."""
    import numpy as np
    polys = drawing(profile)
    if not polys:
        return None
    edges = []
    for poly, _hole in polys:
        n = len(poly)
        for i in range(n):
            edges.append((poly[i][0], poly[i][1], poly[(i + 1) % n][0], poly[(i + 1) % n][1]))
    E = np.array(edges, dtype=float)
    X1, Y1, X2, Y2 = E[:, 0], E[:, 1], E[:, 2], E[:, 3]
    brk = np.unique(np.round(np.concatenate([Y1, Y2]), 12))
    H = brk[-1] - brk[0]
    ym, dy = [], []
    for lo, hi in zip(brk[:-1], brk[1:]):
        k = max(1, int(round(nf * (hi - lo) / H)))
        h = (hi - lo) / k
        ym.extend(lo + (np.arange(k) + 0.5) * h)
        dy.extend([h] * k)
    ym, dy = np.array(ym), np.array(dy)
    width = np.zeros(len(ym))
    for i, y in enumerate(ym):
        m = ((Y1 <= y) & (Y2 > y)) | ((Y2 <= y) & (Y1 > y))
        if not m.any():
            continue
        xs = np.sort(X1[m] + (y - Y1[m]) * (X2[m] - X1[m]) / (Y2[m] - Y1[m]))
        if len(xs) % 2 == 0:
            width[i] = float(np.sum(xs[1::2] - xs[0::2]))
    dA = width * dy
    keep = dA > 0
    ym, dA = ym[keep], dA[keep]
    yc = float(np.sum(dA * ym) / np.sum(dA))
    return ym - yc, dA * (float(profile["A"]) / float(np.sum(dA)))
