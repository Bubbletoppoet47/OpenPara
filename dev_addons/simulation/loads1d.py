"""Wind and snow pressure on frame members (1D FEA tab): plain physics, no code factors.

Every function works in the numbers of the program's unit system (the `unit` name); the pressure is worked out in SI and converted.

  wind   p = 1/2 * rho_air * V^2 * Cp            (V = the whole wind speed; the part across each member is V * cos of the angle)
         on a member with unit direction (c, s) and left normal n = (-s, c), the wind direction w = (cos a, sin a):
         d = w . n,   line load = p * depth * d * |d| * n        (the wind pushes the member toward the side it blows from)
  snow   p = rho_snow * g * h * shape               (h = height of the snow, vertical, downward)
         the snow lies on the horizontal projection, so the load per member length is p * depth * |c|, straight down

`depth` is the in-plane depth of the strip a member carries (its tributary width), a length in the program's unit.
"""
import math

import units

G = 9.80665                               # m/s2
AIR_DENSITY_SI = 1.225                    # kg/m3
SNOW_PRESETS = [("Fresh dry powder", 70.0), ("Settled / packed", 200.0), ("Wet", 350.0), ("Slush / ice", 500.0)]   # kg/m3
DEFAULTS = {"wind": {"V": 30.0, "angle": 0.0, "cp": 1.0}, "snow": {"h": 0.5, "shape": 1.0, "wet": "Settled / packed"}}


def default_load(kind, unit):
    """A starting load of this kind, expressed in the unit system `unit`."""
    if kind == "wind":
        d = DEFAULTS["wind"]
        return {"kind": "wind", "V": units.speed_from_si(d["V"], unit),
                "angle": d["angle"], "cp": d["cp"], "rho": units.density_from_si(AIR_DENSITY_SI, unit)}
    d = DEFAULTS["snow"]
    return {"kind": "snow", "h": d["h"] / units.get(unit)["L_m"], "shape": d["shape"], "rho": units.density_from_si(200.0, unit),
            "wet": d["wet"]}


def pressure(ld, unit):
    """-> (pressure in the unit system's stress unit, pressure in Pa)."""
    if ld["kind"] == "wind":
        pa = 0.5 * units.density_to_si(ld["rho"], unit) * units.speed_to_si(ld["V"], unit) ** 2 * ld["cp"]
    else:
        pa = units.density_to_si(ld["rho"], unit) * G * units.length_to_m(ld["h"], unit) * ld["shape"]
    return units.pressure_from_pa(pa, unit), pa


def wind_vec(c, s, angle_deg, p, depth):
    a = math.radians(angle_deg)
    nx, ny = -s, c
    d = math.cos(a) * nx + math.sin(a) * ny
    f = p * depth * d * abs(d)
    return (f * nx, f * ny), d


def snow_vec(c, p, depth):
    return (0.0, -p * depth * abs(c))


def member_vec(ld, c, s, p, depth):
    if ld["kind"] == "wind":
        return wind_vec(c, s, ld["angle"], p, depth)[0]
    return snow_vec(c, p, depth)


def selftest():
    u = "Metric (m, kg, N, s, Pa)"
    w = {"kind": "wind", "V": 20.0, "angle": 0.0, "cp": 1.0, "rho": 1.225}
    p, pa = pressure(w, u)
    assert abs(pa - 0.5 * 1.225 * 400) < 1e-9
    v = wind_vec(0.0, 1.0, 0.0, p, 2.0)[0]              # a vertical member, wind toward +x
    assert abs(v[0] - 2 * pa) < 1e-9 and abs(v[1]) < 1e-9
    v = wind_vec(1.0, 0.0, 0.0, p, 2.0)[0]              # a horizontal member, wind along it
    assert abs(v[0]) < 1e-12 and abs(v[1]) < 1e-12
    sn = {"kind": "snow", "h": 0.5, "rho": 200.0, "shape": 1.0}
    p, pa = pressure(sn, u)
    assert abs(pa - 200 * G * 0.5) < 1e-9
    v = snow_vec(0.6, p, 3.0)
    assert abs(v[1] + p * 3.0 * 0.6) < 1e-9 and v[0] == 0
    print("loads1d self-test passed")


if __name__ == "__main__":
    selftest()
