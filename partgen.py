"""Part Generator: the catalogue of parts that can be made from a few parameters (no Qt here, so the model can use it).

A part type is a name, a list of parameters and a builder.  Values are kept as text so they can be formulas that use the
Globals (e.g.  Teeth/2); `values(...)` turns them into numbers with the function it is given.
"""
import math

import gears

# a parameter is  (key, label, default, kind, tip)   kind: "float" | "int" | "choice:<a>|<b>|..." | "length" (mm) | "angle" (deg)
SIZE_MODES = [("module", "Module"), ("dp", "Diametral pitch (per inch)"), ("pitch", "Pitch diameter"), ("outside", "Outside diameter")]

GEAR_PARAMS = [
    ("mode", "Size given as", "module", "choice:" + "|".join(v for v, _ in SIZE_MODES), "What the Size box below means; the other sizes are worked out and shown on the right."),
    ("size", "Size", "2", "float", "Module in mm, diametral pitch in teeth per inch, or a diameter in mm, as chosen above."),
    ("teeth", "Number of teeth", "20", "int", "Exactly this many teeth are made."),
    ("pressure", "Pressure angle (deg)", "20", "angle", "Normal pressure angle. 20 is standard."),
    ("width", "Face width (mm)", "10", "length", "How thick the gear is along its axis."),
    ("bore", "Bore diameter (mm)", "8", "length", "Centre hole; 0 for none."),
]
HELIX_PARAMS = [
    ("helix", "Helix angle (deg)", "20", "angle", "Angle of the teeth to the axis, on the pitch cylinder. Module and pressure angle are the normal ones."),
    ("hand", "Hand", "right", "choice:right|left", "A meshing pair has opposite hands."),
]
GROOVE = [("groove", "Centre groove (mm)", "0", "length", "Optional relief groove cut round the middle of a herringbone gear.")]
ADVANCED = [
    ("shift", "Profile shift x", "0", "float", "Moves the cutter out (+) or in (-), in modules. Used to avoid undercut on small gears."),
    ("add", "Addendum factor", "1", "float", "Tooth height above the pitch circle, in modules. Standard 1."),
    ("ded", "Dedendum factor", "1.25", "float", "Tooth depth below the pitch circle, in modules. Standard 1.25."),
    ("backlash", "Backlash (mm)", "0", "length", "Clearance at the pitch circle. Each gear of a pair gives half of it, so use the same value on both."),
]

PART_TYPES = {
    "Spur gear": {"group": "Gears", "params": GEAR_PARAMS, "advanced": ADVANCED},
    "Helical gear": {"group": "Gears", "params": GEAR_PARAMS + HELIX_PARAMS, "advanced": ADVANCED},
    "Herringbone gear": {"group": "Gears", "params": GEAR_PARAMS + HELIX_PARAMS + GROOVE, "advanced": ADVANCED},
}
PLACEMENT = [("plane", "Axis along", "Top"), ("ox", "Offset X (mm)", "0"), ("oy", "Offset Y (mm)", "0"), ("oz", "Offset along axis (mm)", "0")]


def defaults(kind):
    spec = PART_TYPES[kind]
    return {k: d for k, _l, d, _t, _tip in spec["params"] + spec["advanced"]}


def param_defs(kind):
    spec = PART_TYPES[kind]
    return spec["params"], spec["advanced"]


def numbers(kind, raw, num):
    """The parameters as numbers (and strings for the choices).  num(text) evaluates a number / formula."""
    out = {}
    spec = PART_TYPES[kind]
    for k, label, d, t, _tip in spec["params"] + spec["advanced"]:
        v = raw.get(k, d)
        out[k] = str(v) if t.startswith("choice") else (int(round(num(v))) if t == "int" else float(num(v)))
    return out


def gear_inputs(kind, v):
    """Turn the 'Size given as' choice into the module the geometry needs; returns the dict gears.* wants."""
    z = int(v["teeth"])
    beta = math.radians(v["helix"]) if kind != "Spur gear" and "helix" in v else 0.0
    add, x = v["add"], v["shift"]
    size, mode = v["size"], v["mode"]
    if size <= 0:
        raise ValueError("the size must be positive")
    if mode == "module":
        m = size
    elif mode == "dp":
        m = 25.4 / size
    elif mode == "pitch":
        m = size * math.cos(beta) / z
    elif mode == "outside":
        m = size / (z / math.cos(beta) + 2 * (add + x))
    else:
        raise ValueError("unknown size mode")
    p = {"module": m, "teeth": z, "pressure": v["pressure"], "width": v["width"], "bore": v["bore"], "shift": x, "add": add,
         "ded": v["ded"], "backlash": v["backlash"], "helix": 0.0 if kind == "Spur gear" else v["helix"], "hand": v.get("hand", "right"),
         "groove": v.get("groove", 0.0)}
    return p


def build(kind, v):
    """The Solid for a part type and its numbers (axis = Z, from z = 0)."""
    if kind in gears.GEAR_TYPES:
        return gears.make(kind, gear_inputs(kind, v))
    raise ValueError(f"unknown part type {kind}")


def readouts(kind, v):
    """[(label, text)] shown live next to the parameters."""
    if kind in gears.GEAR_TYPES:
        D = gears.dims(gear_inputs(kind, v))
        rows = [("Module (normal)", f"{D['mn']:.4g} mm"), ("Diametral pitch", f"{25.4 / D['mn']:.4g} /in"),
                ("Pitch diameter", f"{D['d']:.4f} mm"), ("Outside diameter", f"{D['da']:.4f} mm"),
                ("Root diameter", f"{D['df']:.4f} mm"), ("Base diameter", f"{D['db']:.4f} mm"),
                ("Circular pitch", f"{D['pitch']:.4f} mm"), ("Base pitch", f"{D['base_pitch']:.4f} mm")]
        if D["beta"]:
            rows.insert(1, ("Transverse module", f"{D['mt']:.4g} mm"))
            rows.append(("Lead", f"{math.pi * D['d'] / math.tan(D['beta']):.2f} mm"))
        return rows
    return []


def warnings(kind, v):
    out = []
    if kind in gears.GEAR_TYPES:
        D = gears.dims(gear_inputs(kind, v))
        if D["undercut"] and v["shift"] <= 0:
            out.append(f"{D['z']} teeth will be undercut at {v['pressure']:g} deg: the tooth roots are weakened. "
                       "Use more teeth, a larger pressure angle or a positive profile shift.")
        if D["rb"] < D["rf"]:
            pass
        bore = v["bore"]
        if bore and bore > 0 and bore > 0.8 * D["df"]:
            out.append("The bore leaves a very thin rim under the teeth.")
    return out


def placed(solid, plane, ox, oy, oz):
    """Move a part built on the Top plane axis-Z to the chosen axis direction and offsets."""
    from build123d import Location, Plane
    base = {"Top": Plane.XY, "Front": Plane.XZ, "Right": Plane.YZ}[plane]
    return solid.moved(Location(base.origin + base.x_dir * ox + base.y_dir * oy + base.z_dir * oz) * Location(base))
