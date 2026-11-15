"""System dynamics tab (dev_addons/dynamics): editor, wiring, checks, examples, files, drag and drop, response, registration."""
import faulthandler
import json
import math
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "dynamics"), os.path.join(HERE, "shared"), HERE]
import numpy as np
from PyQt6.QtCore import QMimeData, QPointF
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import dyn_core as core
import dyn_editor as E
import dyn_parts as P
import dynamics_tab as D

GRID = E.GRID

# ---- part library is complete and consistent ------------------------------------------------------------------------------------------------
for kind, d in P.PARTS.items():
    assert d.cat in P.PALETTE_ORDER and d.pins and all(len(p) == 4 and p[3] in "tr" for p in d.pins), kind
    assert set(P.default_params(kind)) == {q[0] for q in d.params}
assert P.eng(0.5, "kg") == "500 g" and P.eng(2.0, "kg") == "2.00 kg" and P.eng(0.01, "kg·m²") == "0.01 kg·m²" and P.eng(4700, "N/m") == "4700 N/m"
assert P.parse("4.7k") == 4700 and abs(P.parse("100m") - 0.1) < 1e-12 and P.parse("2meg") == 2e6 and abs(P.parse("0.01kg·m²") - 0.01) < 1e-12

# ---- examples load, solve, run ------------------------------------------------------------------------------------------------------------
t = D.make_tab()
t.resize(1400, 800)
t.show()
app.processEvents()
assert t.warn_list.item(0).text() == "No problems found." and "Draw a system" in t.eq_text.toPlainText()
expect = {"Mass, spring and damper": (1, 10.0, 0.5), "Rotating inertia, torsional spring and damper": (1, 10.0, 0.5), "Two masses (two modes)": (2, None, None),
          "Motor + gearbox driving a link": (1, None, None)}
names = list(D.EXAMPLES)
assert set(names) == set(expect)
for i, name in enumerate(names, 1):
    t.load_example(i)
    s = t.model.system
    assert s is not None and not t.model.warnings, (name, t.model.warnings)
    assert len(s.coords) == expect[name][0], name
    if expect[name][1]:
        m = s.modes()[0]
        assert abs(m["wn"] - expect[name][1]) < 1e-6 and abs(m["zeta"] - expect[name][2]) < 1e-6
    assert "EQUATIONS OF MOTION" in t.eq_text.toPlainText() and "POLES" in t.mode_text.toPlainText()
    t.run()
    assert t.run_data is not None and t.plot.data is not None and "Final value" in t.result.text(), (name, t.result.text())
    assert t.out_part.count() >= 1
    t.grab()                                            # painting must not raise
# the motor example: the drawn system settles where the hand formula says
t.load_example(4)
t.run()
s = t.model.system
kg = 0.5 * core.G_ACCEL * 0.2
final = t.plot.data["y"][-1]
assert abs(final - 30 * 0.05 * 6.0 / (2.0 * kg)) / final < 0.03

# the two-mass example has two modes with the textbook frequencies
t.load_example(3)
w = sorted(m["wn"] for m in t.model.system.modes())
M = np.diag([2.0, 1.0])
K = np.array([[320.0, -120.0], [-120.0, 120.0]])
ref = np.sort(np.sqrt(np.linalg.eigvals(np.linalg.solve(M, K)).real))
assert np.allclose(sorted(t.model.system.undamped()), ref, atol=1e-9)

# ---- editing: place, wire, edit values, undo / redo -------------------------------------------------------------------------------------------
t.new()
sc = t.scene
assert not sc.parts()
w1 = sc.add_part("WALL", 0, -GRID)
k1 = sc.add_part("SPRING", 5 * GRID, -4 * GRID)
m1 = sc.add_part("MASS", 11 * GRID, 3 * GRID)
f1 = sc.add_part("FORCE", 15 * GRID, GRID)
assert (w1.name, k1.name, m1.name, f1.name) == ("W1", "k1", "m1", "F1")
t.live()
assert any("not connected" in w for w in t.model.warnings)           # the spring is not wired yet
D._wire(sc, [(0, -1), (0, -4), (2, -4)])
D._wire(sc, [(8, -4), (11, -4), (11, 1)])
D._wire(sc, [(15, -1), (15, -4), (11, -4)])
t.live()
assert len(t.model.warnings) == 1 and "no damping" in t.model.warnings[0], t.model.warnings          # spring + mass only: oscillates forever
assert t.model.system.coords[0]["name"] == "x_m1" and len(t.model.system.inputs) == 1
k1.prm["k"] = 50.0
m1.prm["m"] = 2.0
t.live()
assert abs(t.model.system.modes()[0]["wn"] - 5.0) < 1e-9 and abs(t.model.system.modes()[0]["zeta"]) < 1e-9   # no damper: undamped

# undo / redo of a value change made through the property panel
sc.clearSelection()
m1.setSelected(True)
app.processEvents()
assert t.props_form.rowCount() >= 2
t.set_num(m1, "m", type("W", (), {"text": lambda self: "8", "setText": lambda self, x: None})())
assert m1.prm["m"] == 8.0
sc.undo()
m1b = [p for p in sc.parts() if p.name == "m1"][0]
assert m1b.prm["m"] == 2.0
sc.redo()
assert [p for p in sc.parts() if p.name == "m1"][0].prm["m"] == 8.0
t.rename([p for p in sc.parts() if p.name == "m1"][0], type("W", (), {"text": lambda self: "F1", "setText": lambda self, x: None})())
assert "already used" in t.status.text()

# rotate and mirror keep wires attached, and the system is unchanged
before = t.model.system.modes()[0]["wn"]
part = [p for p in sc.parts() if p.name == "k1"][0]
sc.clearSelection()
part.setSelected(True)
sc.rotate_selected()
sc.rotate_selected(flip=True)
t.live()
assert t.model.system is not None                      # the rotated spring still has wires on its pins
assert part.rot == 1 and part.mirror

# ---- joining straight-line and turning parts is flagged ----------------------------------------------------------------------------------------
t.new()
sc = t.scene
a = sc.add_part("MASS", 0, 0)
b = sc.add_part("INERTIA", 6 * GRID, 0)
D._wire(sc, [(0, -2), (0, -4), (6, -4), (6, -2)])
t.live()
assert any("rack and pinion" in w for w in t.model.warnings) and t.model.system is None
# ... and a node with no mass is reported by name
t.new()
sc = t.scene
sc.add_part("WALL", 0, -GRID)
sc.add_part("SPRING", 5 * GRID, -4 * GRID)
sc.add_part("SPRING", 11 * GRID, -4 * GRID)
sc.add_part("MASS", 17 * GRID, 3 * GRID)
D._wire(sc, [(0, -1), (0, -4), (2, -4)])
D._wire(sc, [(8, -4), (11, -4)])
D._wire(sc, [(14, -4), (17, -4), (17, 1)])
t.live()
assert t.model.system is None and "no mass" in t.model.error and any("no mass" in w for w in t.model.warnings)

# ---- files: save, reopen, same system ---------------------------------------------------------------------------------------------------------------
t.load_example(4)
t.run_time.setText("2")
path = os.path.join(UD, "test.opdyn")
t.path = path
t.save()
assert os.path.isfile(path) and not t.is_dirty()
d = json.load(open(path))
assert d["format"] == "openpara-dynamics" and {p["kind"] for p in d["parts"]} == {"MOTOR", "LINK"} and d["run_time"] == "2"
t2 = D.make_tab(path)
assert t2.title() == "test.opdyn" and t2.run_time.text() == "2" and not t2.is_dirty()
assert np.allclose(np.sort_complex(t2.model.system.poles()), np.sort_complex(t.model.system.poles()))
t2.run()
assert abs(t2.run_data["t"][-1] - 2.0) < 1e-12
t2.edited()
assert t2.is_dirty()

# ---- drag and drop uses the add-on's own mime type (it must not accept a Circuits part) ------------------------------------------------------------
assert E.MIME == "opdyn-part:" and E.MIME != "opcirc-part:"
t3 = D.make_tab()
t3.scene.drop_part("DAMPER", 40.0, 60.0)
assert [p.kind for p in t3.scene.parts()] == ["DAMPER"] and t3.scene.parts()[0].name == "c1"
pal = t3.palette
kinds = []
for i in range(pal.topLevelItemCount()):
    top = pal.topLevelItem(i)
    kinds += [pal.kind_of(top.child(j)) for j in range(top.childCount())]
assert set(kinds) == set(P.PARTS)

# ---- the add-on is described for the app ---------------------------------------------------------------------------------------------------------------
spec = json.load(open(os.path.join(HERE, "dev_addons", "dynamics", "addon.json")))
assert spec["status"] == "workshopping" and spec["tabs"][0]["kind"] == "dynamics" and spec["tabs"][0]["module"] == "dynamics_tab"
assert spec["tabs"][0]["file_types"] == [".opdyn"]
ticks = D.nice_ticks(0, 1.0)
assert ticks[0] == 0 and ticks[-1] == 1.0 and len(ticks) >= 4
print("PASS dynamics tab")
