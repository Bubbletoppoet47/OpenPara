"""thermal_units.py - the thermal quantities in the two unit families (metric, US) and their conversion to SI (no Qt).

Everything that is stored and solved is SI: kelvin, W, m, s, kg, J.  The program's unit system (File > Units) only decides which family the
numbers are SHOWN and TYPED in: a system whose name starts with 'US' uses Btu / hour / foot / degree F, every other one W / metre / degree C.
Lengths are not here: the sketch keeps its own length unit (units.py), as in the 2D FEA.

A temperature is an absolute value (it has an offset); every other quantity is a pure factor.  A temperature DIFFERENCE would be a pure factor too
(1 K = 1 degC = 1.8 degF); nothing here needs one, because the conductivity, coefficient and specific heat units already carry the 'per degree'.
"""
import units

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

    def unit(self, q):
        if q == "T":
            return self.temp
        m, u, _ = QUANTITIES[q]
        return u if self.us else m

    def factor(self, q):
        """SI value of one unit of the family."""
        return QUANTITIES[q][2] if self.us else 1.0

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


def family_of(system):
    """The family of a unit system name (File > Units).  Unknown names are metric."""
    try:
        return Family(units.canon(system).startswith("US"))
    except Exception:                                  # noqa: BLE001
        return Family(False)


def kelvin(value, fam):
    return fam.to_si("T", value)


def temp_text(k, fam, digits=5):
    """A temperature in kelvin as text in the family's degree."""
    return f"{fam.from_si('T', k):.{digits}g} {fam.temp}"
