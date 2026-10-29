"""One unit system for the whole program (sketch, FEA, CFD), chosen in File > Units.

Every system gives, for each quantity, the unit name that is shown and how many SI units one of it is.
Internally the FEA solver works in whatever consistent system the numbers are typed in, and the CFD solver converts to SI.
"""

# name -> dict(L = length unit, F = force, S = stress/pressure, V = speed, rho = density, mu = dynamic viscosity,
#              to_si = metres per length unit, ...)
_SYSTEMS = [
    # name,                          length, m/unit, force, N/unit, stress, Pa/unit, density, (kg/m3)/unit
    ("Metric (m, kg, N, s, Pa)",       "m",   1.0,      "N",   1.0,    "Pa",        1.0,       "kg/m3",   1.0),
    ("Metric (mm, kg, N, s, MPa)",     "mm",  1.0e-3,   "N",   1.0,    "MPa",       1.0e6,     "kg/mm3",  1.0e9),
    ("Metric (mm, kN, kN/mm2)",        "mm",  1.0e-3,   "kN",  1.0e3,  "kN/mm2",    1.0e9,     "kg/mm3",  1.0e9),
    ("US (in, lbf, psi)",              "in",  0.0254,   "lbf", 4.4482216152605, "psi", 6894.757293168, "lbm/in3", 27679.904710203),
    ("US (in, kip, ksi)",              "in",  0.0254,   "kip", 4448.2216152605, "ksi", 6894757.293168, "lbm/in3", 27679.904710203),
    ("US (ft, lbf, psf)",              "ft",  0.3048,   "lbf", 4.4482216152605, "psf", 47.88025898034, "lbm/ft3", 16.018463373960),
    # the same imperial systems with the wind / flow speed in miles per hour
    ("US (in, lbf, psi, mph)",         "in",  0.0254,   "lbf", 4.4482216152605, "psi", 6894.757293168, "lbm/in3", 27679.904710203),
    ("US (in, kip, ksi, mph)",         "in",  0.0254,   "kip", 4448.2216152605, "ksi", 6894757.293168, "lbm/in3", 27679.904710203),
    ("US (ft, lbf, psf, mph)",         "ft",  0.3048,   "lbf", 4.4482216152605, "psf", 47.88025898034, "lbm/ft3", 16.018463373960),
]
MPH = 0.44704                       # metres per second in one mile per hour

DEFAULT = "Metric (mm, kg, N, s, MPa)"
SYSTEMS = {}
_IDS = ["m-N-Pa", "mm-N-MPa", "mm-kN-GPa", "in-lbf-psi", "in-kip-ksi", "ft-lbf-psf",
        "in-lbf-psi-mph", "in-kip-ksi-mph", "ft-lbf-psf-mph"]
BY_ID = {}
for (_n, _l, _lm, _f, _fn, _s, _sp, _d, _dk), _id in zip(_SYSTEMS, _IDS):
    BY_ID[_id] = _n
    SYSTEMS[_n] = {"name": _n, "id": _id, "L": _l, "L_m": _lm, "F": _f, "F_N": _fn, "S": _s, "S_Pa": _sp, "rho": _d, "rho_si": _dk,
                   "V": f"{_l}/s", "V_ms": _lm, "mu": f"{_s} s", "mu_si": _sp}
    if _id.endswith("-mph"):
        SYSTEMS[_n].update({"V": "mph", "V_ms": MPH})


def id_of(name):
    return get(name)["id"]


def name_of(ident):
    """The system name for a short id as written in a sketch file, or None."""
    return BY_ID.get(ident)


def names():
    return list(SYSTEMS)


def get(name):
    return SYSTEMS.get(name) or SYSTEMS[DEFAULT]


def valid(name):
    return name in SYSTEMS


def length_factor(old, new):
    """Multiply a length given in `old` by this to get it in `new`."""
    return get(old)["L_m"] / get(new)["L_m"]


def stress_factor(old, new):
    return get(old)["S_Pa"] / get(new)["S_Pa"]


def force_factor(old, new):
    return get(old)["F_N"] / get(new)["F_N"]


def speed_factor(old, new):
    return get(old)["V_ms"] / get(new)["V_ms"]


def density_factor(old, new):
    return get(old)["rho_si"] / get(new)["rho_si"]


def viscosity_factor(old, new):
    return get(old)["mu_si"] / get(new)["mu_si"]


# ---- to / from SI, used by the CFD solver and the CFD to FEA transfer
def length_to_m(v, name):
    return v * get(name)["L_m"]


def speed_to_si(v, name):
    return v * get(name)["V_ms"]


def speed_from_si(v, name):
    return v / get(name)["V_ms"]


def density_to_si(v, name):
    return v * get(name)["rho_si"]


def density_from_si(v, name):
    return v / get(name)["rho_si"]


def viscosity_to_si(v, name):
    return v * get(name)["mu_si"]


def viscosity_from_si(v, name):
    return v / get(name)["mu_si"]


def pressure_from_pa(v, name):
    return v / get(name)["S_Pa"]


def pressure_to_pa(v, name):
    return v * get(name)["S_Pa"]


def force_per_depth_from_n_per_m(v, name):
    """Force per metre of depth (N/m) -> force per length unit of depth in this system."""
    s = get(name)
    return v * s["L_m"] / s["F_N"]
