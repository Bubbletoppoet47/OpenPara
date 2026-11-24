"""File > Units > Heat transfer: the tables of heatunits.py checked against the meaning of every unit's own name (an independent little unit parser:
value AND dimension), the temperature scales, the presets, the saved setting and its listeners in unitctl, the dialog, and how the main window passes a
change on.  The 2D Thermal tab on these units is in test_thermal_units.py."""
import addons; addons.startup()   # the simulation / render modules live in add-ons
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import json, os, re, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = os.path.join(tmp, "userdata")
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import heatunits as hu
import unitctl, units, paths
import units_dialog
close = lambda a, b, tol=1e-9: abs(a - b) <= tol * max(1.0, abs(a), abs(b))

# ------------------------------------------------------------------------------------------------ 1. every unit means what its name says
# (factor to SI, dimension as (kg, m, s, K)): written out here again, not taken from heatunits
TOK = {"J": (1.0, (1, 2, -2, 0)), "kJ": (1e3, (1, 2, -2, 0)), "cal": (4.1868, (1, 2, -2, 0)), "kcal": (4186.8, (1, 2, -2, 0)),
       "Btu": (1055.05585262, (1, 2, -2, 0)), "kBtu": (1055055.85262, (1, 2, -2, 0)),
       "W": (1.0, (1, 2, -3, 0)), "mW": (1e-3, (1, 2, -3, 0)), "kW": (1e3, (1, 2, -3, 0)), "MW": (1e6, (1, 2, -3, 0)),
       "kg": (1.0, (1, 0, 0, 0)), "g": (1e-3, (1, 0, 0, 0)), "lb": (0.45359237, (1, 0, 0, 0)),
       "m": (1.0, (0, 1, 0, 0)), "cm": (1e-2, (0, 1, 0, 0)), "mm": (1e-3, (0, 1, 0, 0)), "ft": (0.3048, (0, 1, 0, 0)), "in": (0.0254, (0, 1, 0, 0)),
       "s": (1.0, (0, 0, 1, 0)), "hr": (3600.0, (0, 0, 1, 0)), "K": (1.0, (0, 0, 0, 1)), "F": (1 / 1.8, (0, 0, 0, 1))}


def meaning(unit):
    """'Btu in/(hr ft2 F)' -> (value in SI, dimension): the words before the '/' multiply, the words after divide; 'ft2' is ft squared."""
    top, _, bottom = unit.partition("/")
    val, dim = 1.0, [0, 0, 0, 0]
    for part, sign in ((top, 1), (bottom.strip("()"), -1)):
        for tok in part.split():
            m = re.fullmatch(r"([A-Za-z]+)([23]?)", tok)
            f, d = TOK[m.group(1)]
            e = int(m.group(2) or 1) * sign
            val *= f ** e
            dim = [a + b * e for a, b in zip(dim, d)]
    return val, tuple(dim)


WANT = {"P": (1, 2, -3, 0), "q": (1, 0, -3, 0), "qr": (1, 0, -3, 0), "qv": (1, -1, -3, 0), "k": (1, 1, -3, -1), "h": (1, 0, -3, -1),
        "rho": (1, -3, 0, 0), "cp": (0, 2, -2, -1)}
assert hu.QUANTITIES == ["T", "P", "q", "qr", "qv", "k", "h", "rho", "cp"] and set(hu.LABELS) == set(hu.QUANTITIES)
assert meaning("W/(m K)") == (1.0, WANT["k"]) and close(meaning("Btu in/(hr ft2 F)")[0], 0.144227889)      # the parser itself, on a known one
n_units = 0
for q, want in WANT.items():
    assert list(hu.UNITS[q]) == hu.unit_names(q) and len(hu.UNITS[q]) >= 5, q
    for u, si in hu.UNITS[q].items():
        v, dim = meaning(u)
        assert dim == want, (q, u, dim)                                  # a unit of the right kind, in the right list
        assert close(si, v, 1e-12), (q, u, si, v)                         # and worth what its name says
        n_units += 1
assert hu.UNITS["q"] == hu.UNITS["qr"], "the radiative heat flux has the units of a heat flux"
# some of them in words
assert close(hu.UNITS["P"]["Btu/hr"], 0.29307107017, 1e-10) and close(hu.UNITS["P"]["cal/s"], 4.1868) and close(hu.UNITS["P"]["kcal/hr"], 1.163)
assert close(hu.UNITS["k"]["Btu/(hr ft F)"] / hu.UNITS["k"]["Btu in/(hr ft2 F)"], 12.0, 1e-12)            # a foot is 12 inches
assert close(hu.UNITS["k"]["Btu/(s ft F)"] / hu.UNITS["k"]["Btu/(hr ft F)"], 3600.0, 1e-12)
assert close(hu.UNITS["k"]["W/(mm K)"], 1000.0) and close(hu.UNITS["qv"]["W/mm3"], 1e9) and close(hu.UNITS["qv"]["W/in3"], 1 / 0.0254 ** 3)
assert close(hu.UNITS["cp"]["cal/(g K)"], 4186.8) and close(hu.UNITS["cp"]["kcal/(kg K)"], 4186.8) and close(hu.UNITS["cp"]["Btu/(lb F)"], 4186.8, 1e-12)
assert close(hu.UNITS["rho"]["g/cm3"], 1000.0) and close(hu.UNITS["rho"]["lb/ft3"], 16.018463374, 1e-9)
print("1 ok: the tables", n_units, "units")

# ------------------------------------------------------------------------------------------------ 2. temperature scales, round trips
for unit, pairs in {"K": [(0.0, 0.0), (373.15, 373.15)], "°C": [(0.0, 273.15), (100.0, 373.15), (-273.15, 0.0)],
                    "°F": [(32.0, 273.15), (212.0, 373.15), (-459.67, 0.0), (-40.0, 233.15)], "°R": [(0.0, 0.0), (491.67, 273.15), (671.67, 373.15)]}.items():
    for disp, kel in pairs:
        assert abs(hu.to_si("T", unit, disp) - kel) < 1e-9 and abs(hu.from_si("T", unit, kel) - disp) < 1e-9, (unit, disp, kel)
assert abs(hu.to_si("T", "°F", -40.0) - hu.to_si("T", "°C", -40.0)) < 1e-12          # the one temperature where the two scales agree
assert hu.unit_names("T") == ["K", "°C", "°F", "°R"] and hu.is_unit("T", "°R") and not hu.is_unit("T", "degC") and not hu.is_unit("k", "W/m2")
for q in hu.QUANTITIES:
    for u in hu.unit_names(q):
        for v in (-40.0, 0.0, 1.0, 20.0, 1234.5, 3.0e6):
            assert close(hu.from_si(q, u, hu.to_si(q, u, v)), v, 1e-12), (q, u, v)
        if q != "T":
            assert hu.to_si(q, u, 2.0) == 2.0 * hu.si_per_unit(q, u)
print("2 ok: temperature scales and round trips")

# ------------------------------------------------------------------------------------------------ 3. the presets
assert hu.preset_names()[0] == hu.FOLLOW and hu.preset_names()[-1] == hu.CUSTOM and len(hu.preset_names()) == len(hu.PRESETS) + 2 and len(hu.PRESETS) == 9
seen = set()
for name, d in hu.PRESETS.items():
    assert list(d) == hu.QUANTITIES or set(d) == set(hu.QUANTITIES), name
    assert all(hu.is_unit(q, d[q]) for q in hu.QUANTITIES), name
    assert hu.key_of(d) not in seen, f"{name} repeats another preset"
    seen.add(hu.key_of(d))
    assert hu.preset_of(d) == name and hu.resolve(name) == d and hu.resolve(name) is not hu.PRESETS[name]
assert {"°C", "K", "°F", "°R"} == {d["T"] for d in hu.PRESETS.values()}, "every temperature scale is in some preset"
M, U = hu.PRESETS[hu.METRIC], hu.PRESETS[hu.US]
assert (M["T"], M["P"], M["k"], M["h"], M["q"], M["qv"], M["rho"], M["cp"]) == ("°C", "W", "W/(m K)", "W/(m2 K)", "W/m2", "W/m3", "kg/m3", "J/(kg K)")
assert (U["T"], U["P"], U["k"], U["h"], U["q"], U["qv"], U["rho"], U["cp"]) == ("°F", "Btu/hr", "Btu/(hr ft F)", "Btu/(hr ft2 F)", "Btu/(hr ft2)", "Btu/(hr ft3)",
                                                                                  "lb/ft3", "Btu/(lb F)")
# 'Follow the unit system': the US systems use the US preset, every other the metric one
for s in units.names():
    assert hu.resolve(hu.FOLLOW, {}, s) == (U if s.startswith("US") else M), s
assert hu.resolve(hu.FOLLOW, {}, None) == M and hu.resolve("no such preset", {}, "US (in, lbf, psi)") == U and hu.resolve("no such preset", {}, units.DEFAULT) == M
assert hu.is_us_system("US (ft, kip, ksf)") and not hu.is_us_system("Metric (m, kN, kPa)") and not hu.is_us_system(None)
# a custom set: complete and valid whatever comes in
c = hu.resolve(hu.CUSTOM, {"T": "K", "k": "W/(mm K)", "P": "nonsense", "bogus": "x"}, "US (in, lbf, psi)")
assert c["T"] == "K" and c["k"] == "W/(mm K)" and c["P"] == "W" and set(c) == set(hu.QUANTITIES) and hu.resolve(hu.CUSTOM, None, None) == M
assert hu.preset_of(c) == hu.CUSTOM and hu.preset_of({}) == hu.METRIC and hu.preset_of(dict(M, T="K")) == "SI (K, W)"
assert hu.valid_setting("nope", {"T": "K"}) == (hu.FOLLOW, {}) and hu.valid_setting(hu.US, {"T": "K"}) == (hu.US, {})
assert hu.valid_setting(hu.CUSTOM, {"T": "K"})[1] == dict(M, T="K") and hu.valid_setting(None, None) == (hu.FOLLOW, {})
assert hu.key_of(M) != hu.key_of(U) and hu.key_of(M) == hu.key_of(dict(M)) and hu.key_of({}) == hu.key_of(M)
for q in hu.QUANTITIES:                                  # a difference in any one quantity makes two sets different
    other = next(u for u in hu.unit_names(q) if u != M[q])
    assert hu.key_of(dict(M, **{q: other})) != hu.key_of(M), q
print("3 ok: presets")

# ------------------------------------------------------------------------------------------------ 4. unitctl: the saved setting and its listeners
assert unitctl.heat() == hu.FOLLOW and unitctl.heat_custom() == {} and unitctl.heat_setting() == (hu.FOLLOW, {})
assert unitctl.heat_units("Metric (m, kN, kPa)") == M and unitctl.heat_units("US (ft, kip, ksf)") == U
unitctl.set_units(units.DEFAULT, "m/s", notify=False, persist=False)
assert unitctl.heat_units() == M
unitctl.set_units("US (in, lbf, psi)", "m/s", notify=False, persist=False)
assert unitctl.heat_units() == U, "follows the system now in use"
unitctl.set_units(units.DEFAULT, "m/s", notify=False, persist=False)
seen_ = []
seen_listener = lambda o, n: seen_.append((o, n))
unitctl.on_heat_change(seen_listener)
assert unitctl.set_heat("CGS (°C, cal, cm)") is True
assert unitctl.heat() == "CGS (°C, cal, cm)" and unitctl.heat_units() == hu.PRESETS["CGS (°C, cal, cm)"] and unitctl.heat_custom() == {}
assert seen_[0] == ((hu.FOLLOW, {}), ("CGS (°C, cal, cm)", {})), seen_
assert unitctl.set_heat("CGS (°C, cal, cm)") is False and len(seen_) == 1          # no change, no call
assert unitctl.heat_units("US (in, lbf, psi)") == hu.PRESETS["CGS (°C, cal, cm)"], "a preset does not follow the system"
# it is saved in units.json and read again; the system and speed are kept
unitctl.set_units("US (ft, kip, ksf)", "km/h", notify=False, persist=True)
js = json.load(open(unitctl.settings_path()))
assert js["heat"] == "CGS (°C, cal, cm)" and js["heat_custom"] == {} and js["system"] == "US (ft, kip, ksf)" and js["speed"] == "km/h", js
unitctl._state.update(heat=hu.FOLLOW)
r = unitctl.load()
assert r["heat"] == "CGS (°C, cal, cm)" and unitctl.heat() == "CGS (°C, cal, cm)" and r["system"] == "US (ft, kip, ksf)"
# a custom choice
assert unitctl.set_heat(hu.CUSTOM, {"T": "°R", "P": "kW"}) is True
cu = unitctl.heat_units()
assert cu == dict(M, T="°R", P="kW") and unitctl.heat_custom() == cu and unitctl.heat() == hu.CUSTOM
unitctl._state.update(heat=hu.FOLLOW, heat_custom={})
unitctl.load()
assert unitctl.heat() == hu.CUSTOM and unitctl.heat_units() == cu, "the custom units are remembered"
assert unitctl.set_heat(hu.CUSTOM, cu) is False and unitctl.set_heat(hu.CUSTOM) is False, "no argument = the units now chosen"
assert unitctl.set_heat(hu.CUSTOM, {"T": "K"}) is True and unitctl.heat_units() == dict(M, T="K")
assert unitctl.set_heat(hu.US) is True and unitctl.heat_custom() == {}, "a preset leaves no custom units"
assert unitctl.set_heat(hu.CUSTOM) is True and unitctl.heat_units() == U and unitctl.heat() == hu.CUSTOM, "'Custom' without units starts from the units in use"
try:
    unitctl.set_heat("no such choice")
    raise SystemExit("an unknown choice must be refused")
except ValueError:
    pass
# the notification can be switched off, a failing listener does not stop the others, off_heat_change removes one
seen_.clear()
unitctl.set_heat(hu.FOLLOW, notify=False)
assert seen_ == [] and unitctl.heat() == hu.FOLLOW
good = []
bad_l, good_l = (lambda o, n: 1 / 0), (lambda o, n: good.append(n))
unitctl.on_heat_change(bad_l)
unitctl.on_heat_change(good_l)
import contextlib, io
err = io.StringIO()
with contextlib.redirect_stderr(err):
    unitctl.set_heat(hu.US)
assert good == [(hu.US, {})] and "ZeroDivisionError" in err.getvalue(), (good, err.getvalue())
for fn_ in (bad_l, good_l, seen_listener):
    unitctl.off_heat_change(fn_)
assert bad_l not in unitctl._heat_listeners and seen_listener not in unitctl._heat_listeners
# the file of an older program (no heat keys) and a damaged one: 'Follow the unit system'
for text in ('{"system": "US (in, lbf, psi)", "speed": "mph"}', '{"heat": "nonsense", "heat_custom": {"T": "K"}}', '{"heat": "Custom", "heat_custom": {"T": "K", "k": "zzz"}}',
             '{"heat": 7, "heat_custom": 3}', "not json at all"):
    open(unitctl.settings_path(), "w").write(text)
    unitctl.load()
    want = ("Custom", dict(M, T="K")) if '"Custom"' in text else (hu.FOLLOW, {})
    assert unitctl.heat_setting() == want, (text, unitctl.heat_setting())
unitctl.set_heat(hu.FOLLOW, notify=False, persist=True)
assert "heat transfer" in unitctl.system_tip() and hu.FOLLOW in unitctl.system_tip()
print("4 ok: unitctl")

# ------------------------------------------------------------------------------------------------ 5. the dialog
unitctl.set_units(units.DEFAULT, "m/s", notify=False, persist=False)
d = units_dialog.UnitsDialog()
assert d.heat.currentText() == hu.FOLLOW and d.heat_choice() == (hu.FOLLOW, {}) and d.choice() == (units.DEFAULT, "m/s")
assert [d.heat.itemText(i) for i in range(d.heat.count())] == hu.preset_names()
assert list(d.heat_boxes) == hu.QUANTITIES
for q, c in d.heat_boxes.items():
    assert [c.itemText(i) for i in range(c.count())] == hu.unit_names(q), q
assert d.heat_units() == M, "follow: the units of the metric system picked"
d.system.setCurrentText("US (in, lbf, psi)")
assert d.heat.currentText() == hu.FOLLOW and d.heat_units() == U, "follow: the boxes show the units of the system picked now"
d.system.setCurrentText("Metric (m, kN, kPa)")
assert d.heat_units() == M
d.heat.setCurrentText("CGS (°C, cal, cm)")                    # a preset fills every box
assert d.heat_units() == hu.PRESETS["CGS (°C, cal, cm)"] and d.heat_choice() == ("CGS (°C, cal, cm)", {})
d.system.setCurrentText("US (ft, kip, ksf)")
assert d.heat_units() == hu.PRESETS["CGS (°C, cal, cm)"], "a preset does not change with the system"
d.heat_boxes["T"].setCurrentText("K")                          # one unit by hand: not a preset any more
assert d.heat.currentText() == hu.CUSTOM and d.heat_choice() == (hu.CUSTOM, dict(hu.PRESETS["CGS (°C, cal, cm)"], T="K"))
d.heat_boxes["T"].setCurrentText("°C")                         # back to the exact units of a preset: it is that preset
assert d.heat.currentText() == "CGS (°C, cal, cm)" and d.heat_choice()[1] == {}
d.heat_boxes["P"].setCurrentText("kW")
assert d.heat.currentText() == hu.CUSTOM
d.heat.setCurrentText(hu.US)
assert d.heat_units() == U and d.heat_choice() == (hu.US, {})
d.heat.setCurrentText(hu.CUSTOM)                               # picking 'Custom' keeps the units shown
assert d.heat_units() == U and d.heat_choice() == (hu.CUSTOM, U)
# it opens on what is set now, including a custom choice
unitctl.set_heat(hu.CUSTOM, {"T": "°R", "cp": "kJ/(kg K)"}, notify=False, persist=False)
d2 = units_dialog.UnitsDialog()
assert d2.heat.currentText() == hu.CUSTOM and d2.heat_units() == unitctl.heat_units() and d2.heat_boxes["T"].currentText() == "°R"
unitctl.set_heat(hu.US, notify=False, persist=False)
d3 = units_dialog.UnitsDialog()
assert d3.heat.currentText() == hu.US
unitctl.set_heat(hu.FOLLOW, notify=False, persist=False)
print("5 ok: dialog")

# ------------------------------------------------------------------------------------------------ 6. the main window: order, routing, menu
import gpd_app
import pm_model as pm
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
sh = gpd_app.AppShell([])
assert sh.heat_changed in unitctl._heat_listeners and sh.units_changed in unitctl._listeners
from PyQt6.QtWidgets import QWidget


class Bare(QWidget):
    """A document tab with neither unit hook."""
    def title(self):
        return "bare"

    def is_dirty(self):
        return False


class Probe(Bare):
    def __init__(self, log):
        super().__init__()
        self.log = log

    def title(self):
        return "probe"

    def units_changed(self, *a):
        self.log.append(("units", a))

    def heat_changed(self, old, new):
        self.log.append(("heat", old, new))


log = []
sh.tabs.addTab(Probe(log), "probe")
sh.tabs.addTab(Bare(), "no hooks")                      # a tab with neither hook is left alone
unitctl.set_heat("SI (K, W)", notify=True, persist=False)
assert log == [("heat", (hu.FOLLOW, {}), ("SI (K, W)", {}))], log
assert "SI (K, W)" in sh.statusBar().currentMessage()


class FakeDialog(units_dialog.UnitsDialog):
    def exec(self):
        self.system.setCurrentText("US (in, lbf, psi)")
        self.heat.setCurrentText("Metric heating (°C, kcal/hr)")
        return True


units_dialog.UnitsDialog = FakeDialog
log.clear()
sh.units_dialog()
assert unitctl.heat() == "Metric heating (°C, kcal/hr)" and unitctl.system() == "US (in, lbf, psi)"
assert [e[0] for e in log] == ["heat", "units"], "the heat units are told first: with 'Follow the unit system' the new system decides next"
assert log[0][2] == ("Metric heating (°C, kcal/hr)", {})
class Cancel(units_dialog.UnitsDialog):
    def exec(self):
        self.heat.setCurrentText(hu.US)
        return False
units_dialog.UnitsDialog = Cancel
log.clear()
sh.units_dialog()
assert log == [] and unitctl.heat() == "Metric heating (°C, kcal/hr)", "Cancel changes nothing"
unitctl.set_units(units.DEFAULT, "m/s", notify=False, persist=False)
unitctl.set_heat(hu.FOLLOW, notify=False, persist=False)
print("6 ok: main window")
print("ALL HEAT UNIT TESTS PASSED")
