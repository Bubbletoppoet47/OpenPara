"""thermal_mat.py - the thermal material library (no Qt): conductivity, density and specific heat, always stored in SI.

The built-in values are typical room-temperature textbook numbers - check them against your own source.  Materials you add are kept in
thermal_materials.json in your user folder (next to materials.json); the built-in ones cannot be deleted.

A part's own material (Edit Material in the part) has no thermal values, so a slice of a part or an assembly finds each region's conductivity and
specific heat by the NAME of its material (BY_PART_NAME below); the density comes from the part itself when it has one.  A name that is not in the
library leaves the region on the material chosen in the tab, and the tab says so.
"""
import json
import os

# name, conductivity W/(m K), density kg/m3, specific heat J/(kg K)
BUILTIN = [
    ("Structural steel (A36)", 51.9, 7850.0, 486.0),
    ("Steel AISI 1018", 51.9, 7870.0, 486.0),
    ("Stainless steel 304", 16.2, 8000.0, 500.0),
    ("Stainless steel 316", 16.3, 8000.0, 500.0),
    ("Aluminium 6061-T6", 167.0, 2700.0, 896.0),
    ("Aluminium 7075-T6", 130.0, 2810.0, 960.0),
    ("Aluminium 2024-T3", 121.0, 2780.0, 875.0),
    ("Titanium Ti-6Al-4V", 6.7, 4430.0, 526.0),
    ("Copper", 401.0, 8960.0, 385.0),
    ("Brass (cartridge)", 120.0, 8530.0, 380.0),
    ("Gray cast iron", 52.0, 7200.0, 490.0),
    ("Magnesium AZ31B", 96.0, 1770.0, 1000.0),
    ("Nickel alloy (Inconel 718)", 11.4, 8190.0, 435.0),
    ("ABS plastic", 0.17, 1040.0, 1400.0),
    ("Nylon 6/6", 0.25, 1150.0, 1670.0),
    ("Wood (pine)", 0.12, 500.0, 1700.0),
    ("Water (still)", 0.60, 998.0, 4182.0),
    ("Air (still)", 0.026, 1.18, 1005.0),
    ("Concrete", 1.4, 2300.0, 880.0),
    ("Brick", 0.72, 1920.0, 835.0),
    ("Glass (soda-lime)", 1.0, 2500.0, 840.0),
    ("Gypsum board", 0.17, 800.0, 1090.0),
    ("Fiberglass insulation", 0.040, 16.0, 840.0),
    ("Polystyrene foam (EPS)", 0.036, 20.0, 1300.0),
    ("Polyurethane foam", 0.025, 30.0, 1400.0),
]
DEFAULT = "Aluminium 6061-T6"

# the names of the materials of OpenPara parts (mat_lib.BUILTIN) -> the library name
BY_PART_NAME = {
    "Steel (generic)": "Structural steel (A36)", "Structural steel (A36)": "Structural steel (A36)", "Steel AISI 1018": "Steel AISI 1018",
    "Stainless steel": "Stainless steel 304", "Stainless steel 304": "Stainless steel 304", "Stainless steel 316": "Stainless steel 316",
    "Aluminum 6061": "Aluminium 6061-T6", "Aluminum 7075-T6": "Aluminium 7075-T6", "Aluminum 2024-T3": "Aluminium 2024-T3",
    "Titanium": "Titanium Ti-6Al-4V", "Brass": "Brass (cartridge)", "Copper": "Copper", "Cast iron": "Gray cast iron",
    "Magnesium AZ31B": "Magnesium AZ31B", "Nickel alloy (Inconel 718)": "Nickel alloy (Inconel 718)", "ABS plastic": "ABS plastic",
    "Nylon": "Nylon 6/6", "Wood (pine)": "Wood (pine)", "Water": "Water (still)",
}


def _entry(name, k, rho, cp):
    return {"name": name, "k": float(k), "rho": float(rho), "cp": float(cp)}


def builtin():
    return [_entry(*b) for b in BUILTIN]


def builtin_names():
    return {b[0] for b in BUILTIN}


def library_path():
    import paths
    return paths.user_file("thermal_materials.json")


def user_materials():
    """The materials the user added: [{"name", "k", "rho", "cp"}] (an unreadable file gives an empty list)."""
    try:
        with open(library_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for m in data.get("materials", []):
            e = _entry(str(m["name"]), m["k"], m["rho"], m["cp"])
            if e["k"] > 0 and e["rho"] > 0 and e["cp"] > 0 and e["name"] not in builtin_names():
                out.append(e)
        return out
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def library():
    """Built-in and added materials, built-in first."""
    return builtin() + user_materials()


def save_user(materials):
    with open(library_path(), "w", encoding="utf-8") as fh:
        json.dump({"materials": [m for m in materials if m["name"] not in builtin_names()]}, fh, indent=2)


def find(name, lib=None):
    for m in (lib if lib is not None else library()):
        if m["name"] == name:
            return m
    return None


def for_part_material(mat, lib=None):
    """The thermal material of a part's material dict (mat_lib): {"name", "k", "rho", "cp"}, or None when its name is not known.
    The part's own density replaces the library's when it has one."""
    if not mat:
        return None
    name = mat.get("name")
    lib = lib if lib is not None else library()
    m = find(BY_PART_NAME.get(name, name), lib)
    if m is None:
        return None
    m = dict(m)
    d = mat.get("density")
    if isinstance(d, (int, float)) and d > 0:
        m["rho"] = float(d)
    m["name"] = name or m["name"]
    return m
