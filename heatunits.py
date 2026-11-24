"""heatunits.py - the units of the heat-transfer quantities, chosen in File > Units > Heat transfer (no Qt).

Nothing that is stored or solved is in these units: the 2D Thermal tab keeps and solves SI (kelvin, W, m, s, kg).  A unit here only decides how a
number is SHOWN and how a number typed in a box is READ.  Every quantity has its own list of units, and a PRESET is a well-known combination of
them (SI, metric with kW, CGS with calories, US with Btu/hr ...).  A preset called 'Follow the unit system' (the default) uses the US combination
for the US unit systems of File > Units and the metric one for every other, which is what the program did before the group existed.

Quantities (the keys of every dict here):
  T temperature, P heat rate (a heat flow), q heat flux, qr radiative heat flux, qv heat generation per volume, k conductivity,
  h convection coefficient, rho density, cp specific heat.

The constants are the International Table ones (the Btu and the calorie used by engineering tables: 1 Btu/(lb F) = 1 cal/(g K) = 4186.8 J/(kg K)).
A degree of temperature DIFFERENCE is 1 K = 1 degC = 1.8 degF = 1.8 degR, so a unit 'per degree' carries that factor.
"""
K0 = 273.15                                        # 0 degC in kelvin
BTU = 1055.05585262                                # J, International Table Btu
CAL = 4.1868                                       # J, International Table calorie
LB = 0.45359237                                    # kg
FT = 0.3048                                        # m
IN = 0.0254                                        # m
HR = 3600.0                                        # s
DEG = 1.8                                          # degrees F (or R) in one kelvin of difference

QUANTITIES = ["T", "P", "q", "qr", "qv", "k", "h", "rho", "cp"]
LABELS = {"T": "Temperature", "P": "Heat rate", "q": "Heat flux", "qr": "Radiative heat flux", "qv": "Heat generation (per volume)",
          "k": "Conductivity", "h": "Convection coefficient", "rho": "Density", "cp": "Specific heat"}

# temperature: name -> (to kelvin, from kelvin)
TEMPERATURES = {
    "K": (lambda v: v, lambda k: k),
    "°C": (lambda v: v + K0, lambda k: k - K0),
    "°F": (lambda v: (v - 32.0) / DEG + K0, lambda k: (k - K0) * DEG + 32.0),
    "°R": (lambda v: v / DEG, lambda k: k * DEG),
}

_FLUX = {"W/m2": 1.0, "kW/m2": 1e3, "W/cm2": 1e4, "W/mm2": 1e6, "kcal/(hr m2)": 1e3 * CAL / HR, "cal/(s cm2)": CAL / 1e-4,
         "Btu/(hr ft2)": BTU / (HR * FT ** 2), "Btu/(s ft2)": BTU / FT ** 2}

# every other quantity: name -> SI value of one unit
UNITS = {
    "P": {"W": 1.0, "mW": 1e-3, "kW": 1e3, "MW": 1e6, "kcal/hr": 1e3 * CAL / HR, "cal/s": CAL, "Btu/hr": BTU / HR, "kBtu/hr": 1e3 * BTU / HR,
          "Btu/s": BTU},
    "q": dict(_FLUX),
    "qr": dict(_FLUX),
    "qv": {"W/m3": 1.0, "kW/m3": 1e3, "W/cm3": 1e6, "W/mm3": 1e9, "W/in3": 1.0 / IN ** 3, "kcal/(hr m3)": 1e3 * CAL / HR, "cal/(s cm3)": CAL / 1e-6,
           "Btu/(hr ft3)": BTU / (HR * FT ** 3), "Btu/(s ft3)": BTU / FT ** 3},
    "k": {"W/(m K)": 1.0, "W/(cm K)": 1e2, "W/(mm K)": 1e3, "kcal/(hr m K)": 1e3 * CAL / HR, "cal/(s cm K)": CAL / 1e-2,
          "Btu/(hr ft F)": BTU / (HR * FT) * DEG, "Btu/(s ft F)": BTU / FT * DEG, "Btu in/(hr ft2 F)": BTU * IN / (HR * FT ** 2) * DEG},
    "h": {"W/(m2 K)": 1.0, "W/(cm2 K)": 1e4, "W/(mm2 K)": 1e6, "kcal/(hr m2 K)": 1e3 * CAL / HR, "cal/(s cm2 K)": CAL / 1e-4,
          "Btu/(hr ft2 F)": BTU / (HR * FT ** 2) * DEG, "Btu/(s ft2 F)": BTU / FT ** 2 * DEG},
    "rho": {"kg/m3": 1.0, "g/cm3": 1e3, "g/mm3": 1e6, "lb/ft3": LB / FT ** 3, "lb/in3": LB / IN ** 3},
    "cp": {"J/(kg K)": 1.0, "kJ/(kg K)": 1e3, "kcal/(kg K)": 1e3 * CAL, "cal/(g K)": 1e3 * CAL, "Btu/(lb F)": BTU / LB * DEG},
}


def unit_names(q):
    """The units that can be chosen for quantity q, in the order they are listed."""
    return list(TEMPERATURES) if q == "T" else list(UNITS[q])


def si_per_unit(q, unit):
    """SI value of one `unit` of a quantity that is a pure factor (not the temperature)."""
    return UNITS[q][unit]


def to_si(q, unit, v):
    """A number in `unit` -> SI (kelvin for the temperature)."""
    if q == "T":
        return TEMPERATURES[unit][0](v)
    return v * UNITS[q][unit]


def from_si(q, unit, v):
    """An SI number (kelvin for the temperature) -> in `unit`."""
    if q == "T":
        return TEMPERATURES[unit][1](v)
    return v / UNITS[q][unit]


def is_unit(q, unit):
    return unit in (TEMPERATURES if q == "T" else UNITS.get(q, {}))


# ------------------------------------------------------------------------------------------------------------------------------ presets
FOLLOW = "Follow the unit system"
CUSTOM = "Custom"
METRIC = "Metric (°C, W)"
US = "US (°F, Btu/hr)"

PRESETS = {
    METRIC: {"T": "°C", "P": "W", "q": "W/m2", "qr": "W/m2", "qv": "W/m3", "k": "W/(m K)", "h": "W/(m2 K)", "rho": "kg/m3", "cp": "J/(kg K)"},
    "SI (K, W)": {"T": "K", "P": "W", "q": "W/m2", "qr": "W/m2", "qv": "W/m3", "k": "W/(m K)", "h": "W/(m2 K)", "rho": "kg/m3", "cp": "J/(kg K)"},
    "Metric, kilowatts (°C, kW)": {"T": "°C", "P": "kW", "q": "kW/m2", "qr": "kW/m2", "qv": "kW/m3", "k": "W/(m K)", "h": "W/(m2 K)", "rho": "kg/m3",
                                   "cp": "kJ/(kg K)"},
    "Metric, small parts (°C, W, mm)": {"T": "°C", "P": "W", "q": "W/mm2", "qr": "W/mm2", "qv": "W/mm3", "k": "W/(mm K)", "h": "W/(mm2 K)",
                                        "rho": "g/cm3", "cp": "J/(kg K)"},
    "CGS (°C, cal, cm)": {"T": "°C", "P": "cal/s", "q": "cal/(s cm2)", "qr": "cal/(s cm2)", "qv": "cal/(s cm3)", "k": "cal/(s cm K)",
                          "h": "cal/(s cm2 K)", "rho": "g/cm3", "cp": "cal/(g K)"},
    "Metric heating (°C, kcal/hr)": {"T": "°C", "P": "kcal/hr", "q": "kcal/(hr m2)", "qr": "kcal/(hr m2)", "qv": "kcal/(hr m3)", "k": "kcal/(hr m K)",
                                     "h": "kcal/(hr m2 K)", "rho": "kg/m3", "cp": "kcal/(kg K)"},
    US: {"T": "°F", "P": "Btu/hr", "q": "Btu/(hr ft2)", "qr": "Btu/(hr ft2)", "qv": "Btu/(hr ft3)", "k": "Btu/(hr ft F)", "h": "Btu/(hr ft2 F)",
         "rho": "lb/ft3", "cp": "Btu/(lb F)"},
    "US, insulation (°F, Btu in)": {"T": "°F", "P": "Btu/hr", "q": "Btu/(hr ft2)", "qr": "Btu/(hr ft2)", "qv": "Btu/(hr ft3)", "k": "Btu in/(hr ft2 F)",
                                    "h": "Btu/(hr ft2 F)", "rho": "lb/ft3", "cp": "Btu/(lb F)"},
    "US, per second (°R, Btu/s)": {"T": "°R", "P": "Btu/s", "q": "Btu/(s ft2)", "qr": "Btu/(s ft2)", "qv": "Btu/(s ft3)", "k": "Btu/(s ft F)",
                                   "h": "Btu/(s ft2 F)", "rho": "lb/ft3", "cp": "Btu/(lb F)"},
}
DEFAULT = FOLLOW


def preset_names():
    """What the preset list of the dialog shows: 'Follow the unit system', the presets, 'Custom'."""
    return [FOLLOW] + list(PRESETS) + [CUSTOM]


def is_us_system(system):
    """True for the US unit systems of File > Units (their names start with 'US')."""
    return str(system or "").startswith("US")


def clean(units_by_q):
    """A dict with a valid unit for every quantity: unknown or missing entries become the metric preset's."""
    src = units_by_q if isinstance(units_by_q, dict) else {}
    return {q: (src[q] if is_unit(q, src.get(q)) else PRESETS[METRIC][q]) for q in QUANTITIES}


def resolve(preset, custom=None, system=None):
    """The unit of every quantity for a heat setting: -> {quantity: unit name}.  `preset` is FOLLOW, a name of PRESETS, or CUSTOM (then `custom` says
    the units; a missing one is the metric preset's).  `system` is the unit system of File > Units (needed by FOLLOW only).  An unknown preset
    is treated like FOLLOW."""
    if preset == CUSTOM:
        return clean(custom)
    if preset in PRESETS:
        return dict(PRESETS[preset])
    return dict(PRESETS[US if is_us_system(system) else METRIC])


def preset_of(units_by_q):
    """The name of the preset these units are (the first one that matches), or CUSTOM."""
    u = clean(units_by_q)
    for n, d in PRESETS.items():
        if d == u:
            return n
    return CUSTOM


def valid_setting(preset, custom):
    """A saved heat setting made safe: -> (preset name, custom dict).  A preset that does not exist becomes FOLLOW; the custom units are only
    kept for CUSTOM (and are complete and valid then)."""
    p = preset if preset in preset_names() else FOLLOW
    return p, (clean(custom) if p == CUSTOM else {})


def key_of(units_by_q):
    """A hashable form of a set of units, to compare two sets."""
    u = clean(units_by_q)
    return tuple(u[q] for q in QUANTITIES)
