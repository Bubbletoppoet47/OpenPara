"""One unit system for the whole program (sketch, FEA, CFD), chosen in File > Units.

Every system gives, for each quantity, the unit name that is shown and how many SI units one of it is.
Internally the FEA solver works in whatever consistent system the numbers are typed in, and the CFD solver converts to SI.
"""

# name -> dict(L = length unit, F = force, S = stress/pressure, V = speed, rho = density, mu = dynamic viscosity,
#              to_si = metres per length unit, ...)
# The SPEED is not part of the system: it is its own global setting (set_speed), so the lists do not multiply.
_SYSTEMS = [
    # name,                          length, m/unit, force, N/unit, stress, Pa/unit, density, (kg/m3)/unit
    ("Metric (m, kg, N, s, Pa)",       "m",   1.0,      "N",   1.0,    "Pa",        1.0,       "kg/m3",   1.0),
    ("Metric (mm, kg, N, s, MPa)",     "mm",  1.0e-3,   "N",   1.0,    "MPa",       1.0e6,     "kg/mm3",  1.0e9),
    ("Metric (mm, kN, kN/mm2)",        "mm",  1.0e-3,   "kN",  1.0e3,  "kN/mm2",    1.0e9,     "kg/mm3",  1.0e9),
    ("US (in, lbf, psi)",              "in",  0.0254,   "lbf", 4.4482216152605, "psi", 6894.757293168, "lbm/in3", 27679.904710203),
    ("US (in, kip, ksi)",              "in",  0.0254,   "kip", 4448.2216152605, "ksi", 6894757.293168, "lbm/in3", 27679.904710203),
    ("US (ft, lbf, psf)",              "ft",  0.3048,   "lbf", 4.4482216152605, "psf", 47.88025898034, "lbm/ft3", 16.018463373960),
    ("Metric (cm, kg, N, s, N/cm2)",   "cm",  1.0e-2,   "N",   1.0,    "N/cm2",     1.0e4,     "kg/cm3",  1.0e6),
    ("Metric (m, kN, kPa)",            "m",   1.0,      "kN",  1.0e3,  "kPa",       1.0e3,     "t/m3",    1.0e3),
    ("US (ft, kip, ksf)",              "ft",  0.3048,   "kip", 4448.2216152605, "ksf", 47880.25898034, "lbm/ft3", 16.018463373960),
]
DEFAULT = "Metric (mm, kg, N, s, MPa)"
SYSTEMS = {}
_IDS = ["m-N-Pa", "mm-N-MPa", "mm-kN-GPa", "in-lbf-psi", "in-kip-ksi", "ft-lbf-psf", "cm-N-Ncm2", "m-kN-kPa", "ft-kip-ksf"]
BY_ID = {}
for (_n, _l, _lm, _f, _fn, _s, _sp, _d, _dk), _id in zip(_SYSTEMS, _IDS):
    BY_ID[_id] = _n
    SYSTEMS[_n] = {"name": _n, "id": _id, "L": _l, "L_m": _lm, "F": _f, "F_N": _fn, "S": _s, "S_Pa": _sp, "rho": _d, "rho_si": _dk,
                   "V": "m/s", "V_ms": 1.0, "mu": f"{_s} s", "mu_si": _sp}

# Older files named three systems "... mph" (the system and the speed unit were one choice).  They are the same system now;
# the speed unit of such a file is mph (see legacy_speed_unit).
_ALIAS = {"US (in, lbf, psi, mph)": "US (in, lbf, psi)", "US (in, kip, ksi, mph)": "US (in, kip, ksi)",
          "US (ft, lbf, psf, mph)": "US (ft, lbf, psf)"}
for _i, _t in (("in-lbf-psi-mph", "US (in, lbf, psi)"), ("in-kip-ksi-mph", "US (in, kip, ksi)"), ("ft-lbf-psf-mph", "US (ft, lbf, psf)")):
    BY_ID[_i] = _t

# ---- the speed unit (a global setting, independent of the system)
MPH = 0.44704                       # metres per second in one mile per hour
SPEEDS = {"m/s": 1.0, "km/h": 1.0 / 3.6, "mph": MPH, "ft/s": 0.3048, "mm/s": 1.0e-3, "in/s": 0.0254}
DEFAULT_SPEED = "m/s"
_speed = DEFAULT_SPEED


def speed_names():
    return list(SPEEDS)


def speed_unit():
    return _speed


def set_speed(u):
    """Make `u` the speed unit of the whole program (the V / V_ms entries of every system follow)."""
    global _speed
    if u not in SPEEDS:
        raise ValueError(f"unknown speed unit '{u}'")
    _speed = u
    for d in SYSTEMS.values():
        d["V"], d["V_ms"] = u, SPEEDS[u]


def speed_per_si(u):
    return SPEEDS[u]


def legacy_speed_unit(system_name):
    """The speed unit a file without a stored one used: mph for the three old '... mph' systems, else one length unit per second."""
    n = str(system_name or "")
    if n in _ALIAS:
        return "mph"
    d = SYSTEMS.get(n)
    if d is None:
        return "mm/s"
    u = f"{d['L']}/s"
    return u if u in SPEEDS else "m/s"


def canon(name):
    return _ALIAS.get(name, name)


set_speed(DEFAULT_SPEED)


def id_of(name):
    return get(name)["id"]


def name_of(ident):
    """The system name for a short id as written in a sketch file, or None."""
    return BY_ID.get(ident)


def names():
    return list(SYSTEMS)


def get(name):
    return SYSTEMS.get(canon(name)) or SYSTEMS[DEFAULT]


def valid(name):
    return canon(name) in SYSTEMS


def length_factor(old, new):
    """Multiply a length given in `old` by this to get it in `new`."""
    return get(old)["L_m"] / get(new)["L_m"]


def stress_factor(old, new):
    return get(old)["S_Pa"] / get(new)["S_Pa"]


def force_factor(old, new):
    return get(old)["F_N"] / get(new)["F_N"]


def speed_factor(old, new):
    """Multiply a speed in speed unit `old` by this to get it in `new` (speed unit names, e.g. 'mph' -> 'm/s')."""
    return SPEEDS[old] / SPEEDS[new]


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
