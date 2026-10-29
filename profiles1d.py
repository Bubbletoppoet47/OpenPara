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


def compute(key, dims, flip=False, weak=False):
    """-> profile dict (see the module text).  Raises ValueError with a message for the user."""
    if key not in _BY_KEY:
        raise ValueError(f"Unknown shape '{key}'.")
    d = {}
    for k, _, _ in _BY_KEY[key][2]:
        if k not in dims:
            raise ValueError(f"Missing dimension '{k}'.")
        d[k] = float(dims[k])
    _check(key, d)
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
            rot = lambda poly: [(-y, x) for x, y in poly]
            faces = [{"poly": rot(f["poly"]), "holes": [{"poly": rot(h["poly"])} for h in f["holes"]]} for f in faces]
        pr = secp.properties(faces)
        A, I, ct, cb = pr["area"], pr["Ixx"], pr["c_top"], pr["c_bottom"]
    if flip:
        ct, cb = cb, ct
    if not (A > 0 and I > 0 and ct > 0 and cb > 0):
        raise ValueError("The section has no area, no stiffness, or a fibre distance of zero.")
    label = make_label(key, d) + (" (weak axis)" if weak and key not in ("round", "pipe", "custom") else "") + (" (flipped)" if flip else "")
    return {"shape": key, "dims": d, "flip": bool(flip), "weak": bool(weak), "A": A, "I": I, "c_top": ct, "c_bottom": cb, "label": label}


def drawing(profile, n_circle=48):
    """Faces (outer polygon + holes) to draw the section, in the profile's own units, y up, as a list of polygons with a flag:
    [(polygon, is_hole)].  A section entered by numbers has no drawing (returns [])."""
    key = profile.get("shape")
    if key in (None, "custom", "imported"):
        return []
    d = profile["dims"]
    faces = _faces(key, d)
    if profile.get("weak") and key not in ("round", "pipe"):
        rot = lambda poly: [(-y, x) for x, y in poly]
        faces = [{"poly": rot(f["poly"]), "holes": [{"poly": rot(h["poly"])} for h in f["holes"]]} for f in faces]
    out = []
    for f in faces:
        out.append((f["poly"], False))
        for h in f["holes"]:
            out.append((h["poly"], True))
    if profile.get("flip"):
        out = [([(x, -y) for x, y in poly], hole) for poly, hole in out]
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
    return compute(profile["shape"], dims, profile.get("flip", False), profile.get("weak", False))
