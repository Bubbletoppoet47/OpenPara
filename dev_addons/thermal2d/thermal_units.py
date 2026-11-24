"""thermal_units.py - the thermal quantities in the units of File > Units > Heat transfer and their conversion to SI (no Qt).

Everything that is stored and solved is SI: kelvin, W, m, s, kg, J.  File > Units only decides which units the numbers are SHOWN and TYPED in.  The
heat-transfer group of that dialog (heatunits.py) gives a unit to every thermal quantity, as a preset (SI, metric with kW, CGS with calories, US
with Btu ...) or one by one.  Its default, 'Follow the unit system', is what this module always did: a unit system whose name starts with 'US' uses
Btu / hour / foot / degree F, every other one W / metre / degree C.
Lengths are not here: the sketch keeps its own length unit (units.py), as in the 2D FEA.

A temperature is an absolute value (it has an offset); every other quantity is a pure factor.  A temperature DIFFERENCE would be a pure factor too
(1 K = 1 degC = 1.8 degF); nothing here needs one, because the conductivity, coefficient and specific heat units already carry the 'per degree'.
"""
import units

try:
    import heatunits as hu
except ImportError:                                # a program from before File > Units > Heat transfer: the two families below, chosen by the unit system
    hu = None

K0 = 273.15                                        # 0 degC in kelvin
SIGMA = 5.670374419e-8                             # Stefan-Boltzmann constant, W/(m2 K4)

# quantity -> (metric label, US label, US value in SI per 1 US unit)
QUANTITIES = {
    "k":   ("W/(m K)",    "Btu/(hr ft F)",     1.730734666),     # conductivity
    "h":   ("W/(m2 K)",   "Btu/(hr ft2 F)",    5.678263341),     # convection coefficient
    "q":   ("W/m2",       "Btu/(hr ft2)",      3.154590745),     # heat flux
    "qv":  ("W/m3",       "Btu/(hr ft3)",      10.34970717),     # heat generation per volume
    "rho": ("kg/m3",      "lb/ft3",            16.01846337),     # density
    "cp":  ("J/(kg K)",   "Btu/(lb F)",        4186.8),          # specific heat
    "P":   ("W",          "Btu/hr",            0.2930710702),    # a heat flow
}
TIME = {"s": 1.0, "min": 60.0, "h": 3600.0}        # the time unit is its own choice (the heat flow units are per second / per hour already)


class Family:
    """The unit family of a unit system: .us (True / False), .temp ('°C' / '°F'), .unit(q), .to_si(q, v), .from_si(q, v)."""

    def __init__(self, us):
        self.us = bool(us)
        self.name = "US (Btu, hr, ft, °F)" if self.us else "Metric (W, m, °C)"
        self.temp = "°F" if self.us else "°C"
        self.key = ("family", self.us)

    def unit(self, q):
        if q == "T":
            return self.temp
        m, u, _ = QUANTITIES["q" if q == "qr" else q]
        return u if self.us else m

    def factor(self, q):
        """SI value of one unit of the family."""
        return QUANTITIES["q" if q == "qr" else q][2] if self.us else 1.0

    def to_si(self, q, v):
        if q == "T":
            return (v - 32.0) / 1.8 + K0 if self.us else v + K0
        return v * self.factor(q)

    def from_si(self, q, v):
        if q == "T":
            return (v - K0) * 1.8 + 32.0 if self.us else v - K0
        return v / self.factor(q)

    def temp_difference_to_si(self, d):
        return d / 1.8 if self.us else d


class UnitSet:
    """The unit of every thermal quantity (heatunits.QUANTITIES): .unit(q), .to_si(q, v), .from_si(q, v), .factor(q), .temp ('°C' ...), .name, .key.
    Used like Family, which is what this module had before the units could be chosen one by one."""

    def __init__(self, units_by_q):
        self.units = hu.clean(units_by_q)
        self.key = hu.key_of(self.units)
        self.temp = self.units["T"]
        self.name = hu.preset_of(self.units)
        self.us = self.temp in ("°F", "°R")            # the temperature is a Fahrenheit-size degree (older callers)

    def unit(self, q):
        return self.units[q]

    def factor(self, q):
        """SI value of one unit of a quantity that is a pure factor."""
        return hu.si_per_unit(q, self.units[q])

    def to_si(self, q, v):
        return hu.to_si(q, self.units[q], v)

    def from_si(self, q, v):
        return hu.from_si(q, self.units[q], v)

    def temp_difference_to_si(self, d):
        return d / hu.DEG if self.temp in ("°F", "°R") else d


_SETS = {}


def unit_set(units_by_q):
    """The UnitSet of a dict of units (the same object for the same units)."""
    u = hu.clean(units_by_q)
    k = hu.key_of(u)
    if k not in _SETS:
        _SETS[k] = UnitSet(u)
    return _SETS[k]


def current_setting():
    """The heat-transfer choice made in File > Units: (name, custom units).  'Follow the unit system' when the program has no such choice."""
    try:
        import unitctl
        return unitctl.heat_setting()
    except Exception:                                  # noqa: BLE001
        return (hu.FOLLOW, {}) if hu is not None else ("", {})


def family_of(system, setting=None):
    """The units for a unit system name (File > Units) under the heat-transfer choice made there (or `setting`, a (name, custom units) pair).
    Unknown system names are metric."""
    try:
        us = units.canon(system).startswith("US")
    except Exception:                                  # noqa: BLE001
        us = False
    if hu is None:
        return Family(us)
    name, custom = setting if setting is not None else current_setting()
    return unit_set(hu.resolve(name, custom, "US" if us else "Metric"))


def follow_of(system):
    """The units a document of this unit system had before the choice existed (a US system: Btu and degree F; any other: W and degree C)."""
    return family_of(system, (hu.FOLLOW, {}) if hu is not None else None)


def state_family(st, system):
    """The units the numbers in the boxes of a saved state are written in: the ones it says, or, for a state saved before they were recorded,
    the ones its unit system had."""
    d = st.get("heat_units") if isinstance(st, dict) else None
    if hu is not None and isinstance(d, dict):
        return unit_set(d)
    return follow_of(system)


def kelvin(value, fam):
    return fam.to_si("T", value)


def temp_text(k, fam, digits=5):
    """A temperature in kelvin as text in the family's degree."""
    return f"{fam.from_si('T', k):.{digits}g} {fam.temp}"
