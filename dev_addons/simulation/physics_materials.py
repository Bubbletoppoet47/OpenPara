"""
Physics Calc - material library and unit conversion.

materials.json (next to the program) holds the library, always in MPa:
    {"materials": [{"name": "Aluminium 6061-T6", "E_MPa": 68900, "nu": 0.33}, ...]}
It is created with typical values the first time; edit it by hand, or use the Add / Delete buttons.
The values that ship are typical textbook numbers - check them against your own source.
"""
import json
import os

import units

# unit system name (the program-wide choice, see units.py) -> (stress unit name, how many of that unit make 1 MPa)
UNITS = {n: (u["S"], 1.0e6 / u["S_Pa"]) for n, u in units.SYSTEMS.items()}
DEFAULT_UNIT = units.DEFAULT

DEFAULTS = [
    ("Structural steel (A36)", 200000.0, 0.26),
    ("Steel AISI 1018", 205000.0, 0.29),
    ("Stainless steel 304", 193000.0, 0.29),
    ("Stainless steel 316", 193000.0, 0.30),
    ("Aluminium 6061-T6", 68900.0, 0.33),
    ("Aluminium 7075-T6", 71700.0, 0.33),
    ("Aluminium 2024-T3", 73100.0, 0.33),
    ("Titanium Ti-6Al-4V", 113800.0, 0.342),
    ("Copper", 117000.0, 0.34),
    ("Brass (cartridge)", 110000.0, 0.34),
    ("Gray cast iron", 110000.0, 0.26),
    ("Magnesium AZ31B", 45000.0, 0.35),
    ("Nickel alloy (Inconel 718)", 200000.0, 0.29),
]

# typical (yield, ultimate) strengths in MPa; yield 0 = brittle (no yielding, ultimate only)
STRENGTH = {
    "Structural steel (A36)": (250, 400), "Steel AISI 1018": (370, 440), "Stainless steel 304": (215, 505),
    "Stainless steel 316": (205, 515), "Aluminium 6061-T6": (276, 310), "Aluminium 7075-T6": (503, 572),
    "Aluminium 2024-T3": (345, 483), "Titanium Ti-6Al-4V": (880, 950), "Copper": (70, 220), "Brass (cartridge)": (125, 340),
    "Gray cast iron": (0, 200), "Magnesium AZ31B": (200, 260), "Nickel alloy (Inconel 718)": (1030, 1240),
}
EPS_U_DEFAULT = 0.10     # typical plastic strain at the ultimate strength (a 10 % round figure for ductile metals)


def library_path():
    import paths
    return paths.user_file("materials.json")


def to_mpa(value, unit):
    return value / UNITS[unit][1]


def from_mpa(value_mpa, unit):
    return value_mpa * UNITS[unit][1]


def _entry(name, e, nu, sy=None, su=None, eps_u=None):
    """A library entry.  A material that has no strengths stored keeps None (the FEA tab then leaves its strength boxes alone and
    says so); the built-in ones get their typical values."""
    d_sy, d_su = STRENGTH.get(name, (None, None))
    out = {"name": name, "E_MPa": e, "nu": nu, "Sy_MPa": d_sy if sy is None else sy, "Su_MPa": d_su if su is None else su}
    if eps_u is not None:
        out["eps_u"] = eps_u
    return out


def load():
    """-> list of {"name", "E_MPa", "nu", "Sy_MPa", "Su_MPa"}.  Creates the file with typical values when it is missing."""
    path = library_path()
    if not os.path.isfile(path):
        save([_entry(n, e, v) for n, e, v in DEFAULTS])
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        out = []
        for m in data.get("materials", []):
            out.append(_entry(str(m["name"]), float(m["E_MPa"]), float(m["nu"]),
                              float(m["Sy_MPa"]) if m.get("Sy_MPa") is not None else None,
                              float(m["Su_MPa"]) if m.get("Su_MPa") is not None else None,
                              float(m["eps_u"]) if m.get("eps_u") is not None else None))
        return out
    except Exception:
        return [_entry(n, e, v) for n, e, v in DEFAULTS]


def save(materials):
    with open(library_path(), "w", encoding="utf-8") as fh:
        json.dump({"materials": materials}, fh, indent=2)
