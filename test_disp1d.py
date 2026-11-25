"""The Displacement support of the 1D FEA window: blank = free, 0 = held, a number = imposed (x and y in the length unit of the window, the rotation in degrees).
Beam-theory known answers (a member 1000 long, rectangle 20 x 40, one element - the cubic is exact for an end movement):
  fixed at one end, the other end moved by d across and free to turn   R = 3 E I d / L^3 at the moved end, M = 3 E I d / L^2 at the wall
  fixed at both ends, one end settles by d                              R = 12 E I d / L^3, M = 6 E I d / L^2
  fixed at one end, the other end pinned, the wall turned by theta      M = 3 E I theta / L, R = 3 E I theta / L^2
  a bar moved at its end by d                                           R = E A d / L
Old files: 'ux = 0' / 'uy = 0' open as a Displacement; the nonlinear solver reaches the same numbers; the table, the dialog, the unit change, the study."""
import os, sys, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
import sketcher_core as sc
import beam_tab, sim_tab, profiles1d, sim_disp, beam1d
import physics_store as pstore

host = sim_tab.SimHost.__new__(sim_tab.SimHost)
host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
host.sketch_list = lambda: []


def new_tab():
    b = beam_tab.BeamTab(host)
    bm = sc.Model(); q = [bm.add_point(0, 0), bm.add_point(1000, 0)]; bm.add_line(q[0], q[1])
    b.set_model(bm, "beam")
    b.set_profiles([0], profiles1d.compute("rect", {"b": 20.0, "h": 40.0}))
    return b, q


b, q = new_tab()
E = float(b.e_E.text()); I = 20 * 40 ** 3 / 12.0; A = 20 * 40.0; L = 1000.0
a, z = q


def solve(supports, loads=()):
    b.supports = [dict(s) for s in supports]
    b.loads = [dict(l) for l in loads]
    assert b.solve(auto=True), b.res_lbl.text()
    return b.result


def close(x, y, tol=1e-6):
    return abs(x - y) <= tol * max(abs(y), 1e-12)


FIXED = {"mode": "fixed", "targets": [a]}
# ----------------------------------------------------------------------------------------------------------------- the buttons
sec = [x for x in b.sections if x.title == "Supports"][0]
assert [bt.text().strip() for bt in sec.frame.findChildren(QPushButton)] == ["Fixed", "Pinned", "Displacement..."]
assert sim_disp.KEYS[1] == ("ux", "uy", "rz")

# ----------------------------------------------------------------------------------------------------------------- the end moved across, free to turn
d = 2.0
res = solve([FIXED, {"mode": "disp", "targets": [z], "ux": None, "uy": d, "rz": None}])
assert close(res["nodes"][z][1], d, 1e-9), res["nodes"][z]
assert close(res["reactions"][z][1], 3 * E * I * d / L ** 3), (res["reactions"][z], 3 * E * I * d / L ** 3)
assert close(abs(res["reactions"][a][2]), 3 * E * I * d / L ** 2), res["reactions"][a]
assert res["reactions"][z][0] == 0.0 and res["reactions"][z][2] == 0.0, "the free directions carry nothing"
assert res["equilibrium"]["relative"] < 1e-9, res["equilibrium"]
# the same end pushed by the force of that size moves exactly as far
P = 3 * E * I * d / L ** 3
res2 = solve([FIXED, {"mode": "disp", "targets": [z], "ux": None, "uy": 0.0, "rz": None}], [{"kind": "force", "fx": 0.0, "fy": P, "targets": [z]}])
assert abs(res2["nodes"][z][1]) < 1e-9, "held at 0 it does not move"
res2b = solve([FIXED], [{"kind": "force", "fx": 0.0, "fy": P, "targets": [z]}])
assert close(res2b["nodes"][z][1], d, 1e-6), res2b["nodes"][z]
assert close(res2b["nodes"][z][2], res["nodes"][z][2], 1e-6), "the same end rotation too"
# the number is the size AND the direction: a negative number moves it the other way
res3 = solve([FIXED, {"mode": "disp", "targets": [z], "ux": None, "uy": -d, "rz": None}])
assert close(res3["reactions"][z][1], -P) and close(res3["nodes"][z][1], -d, 1e-9)

# ----------------------------------------------------------------------------------------------------------------- fixed at both ends, one end settles
res = solve([FIXED, {"mode": "disp", "targets": [z], "ux": 0.0, "uy": -d, "rz": 0.0}])
assert close(abs(res["reactions"][z][1]), 12 * E * I * d / L ** 3) and close(abs(res["reactions"][z][2]), 6 * E * I * d / L ** 2), res["reactions"][z]
assert close(res["nodes"][z][1], -d, 1e-9) and res["nodes"][z][2] == 0.0
# the end is held in rotation but not in height: no settlement force at all
res = solve([FIXED, {"mode": "disp", "targets": [z], "ux": 0.0, "uy": None, "rz": 0.0}])
assert abs(res["reactions"][z][1]) == 0.0 and abs(res["nodes"][z][1]) < 1e-12

# ----------------------------------------------------------------------------------------------------------------- the wall turned, the far end pinned
theta = 0.5                                                                   # degrees
th = math.radians(theta)
res = solve([{"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": theta}, {"mode": "pinned", "targets": [z]}])
assert close(res["nodes"][a][2], th, 1e-9), res["nodes"][a]
assert close(abs(res["reactions"][a][2]), 3 * E * I * th / L), (res["reactions"][a], 3 * E * I * th / L)
assert close(abs(res["reactions"][z][1]), 3 * E * I * th / L ** 2), res["reactions"][z]
# the same with a Fixed wall and the end moved, in other words: the signs follow (counter-clockwise positive)
res_n = solve([{"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": -theta}, {"mode": "pinned", "targets": [z]}])
assert close(res_n["nodes"][a][2], -th, 1e-9) and close(res_n["reactions"][a][2], -res["reactions"][a][2])

# ----------------------------------------------------------------------------------------------------------------- a bar moved along its axis
dx = 0.4
res = solve([FIXED, {"mode": "disp", "targets": [z], "ux": dx, "uy": 0.0, "rz": 0.0}])
assert close(res["reactions"][z][0], E * A * dx / L) and close(res["nodes"][z][0], dx, 1e-9), res["reactions"][z]
assert abs(res["members"][0]["N_peak"] - E * A * dx / L) < 1e-6 * E * A * dx / L

# ----------------------------------------------------------------------------------------------------------------- the mesh does not change the answer
b.e_nel.setText("4")
res4 = solve([FIXED, {"mode": "disp", "targets": [z], "ux": None, "uy": d, "rz": None}])
assert close(res4["reactions"][z][1], 3 * E * I * d / L ** 3, 1e-6) and close(res4["nodes"][z][1], d, 1e-9)
b.e_nel.setText("1")

# ----------------------------------------------------------------------------------------------------------------- the nonlinear solver (a small movement: the same answer)
b.cb_nl.setChecked(True); b.cb_lin.setChecked(False)
res5 = solve([FIXED, {"mode": "disp", "targets": [z], "ux": None, "uy": d, "rz": None}])
assert res5["nl"] is not None and res5["nl"]["converged"], res5.get("nl")
assert abs(res5["reactions"][z][1] - 3 * E * I * d / L ** 3) / (3 * E * I * d / L ** 3) < 0.01, (res5["reactions"][z], 3 * E * I * d / L ** 3)
assert abs(res5["nodes"][z][1] - d) < 1e-6, res5["nodes"][z]
res6 = solve([{"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": theta}, {"mode": "pinned", "targets": [z]}])
assert res6["nl"] is not None and abs(abs(res6["reactions"][a][2]) - 3 * E * I * th / L) / (3 * E * I * th / L) < 0.01, res6["reactions"][a]
assert abs(res6["nodes"][a][2] - th) < 1e-9
b.cb_nl.setChecked(False); b.cb_lin.setChecked(True)

# ----------------------------------------------------------------------------------------------------------------- no support that holds anything, and the old holds
b.supports = []
assert not b.solve(auto=True) and "Displacement" in b.res_lbl.text()
b.supports = [{"mode": "x", "targets": [a]}, {"mode": "y", "targets": [a]}, {"mode": "fixed", "targets": [z]}]       # an old file
st = b.export_state()
b2 = beam_tab.BeamTab(host); b2.import_state(st)
assert b2.supports[0]["mode"] == "disp" and b2.supports[0]["ux"] == 0.0 and b2.supports[0]["uy"] is None and b2.supports[0]["rz"] is None, b2.supports[0]
assert b2.supports[1]["mode"] == "disp" and b2.supports[1]["ux"] is None and b2.supports[1]["uy"] == 0.0 and b2.supports[1]["rz"] is None
assert b2.supports[2]["mode"] == "fixed"
# ... and gives what the old holds gave: the end a is held in x and in y (a pin, by two supports), z is fixed, loaded across
old = solve(b.supports, [{"kind": "force", "fx": 0.0, "fy": -300.0, "targets": [z]}])
new = solve(b2.supports, [{"kind": "force", "fx": 0.0, "fy": -300.0, "targets": [z]}])
assert abs(old["nodes"][z][1] - new["nodes"][z][1]) < 1e-12 and old["reactions"][a] == new["reactions"][a]
# the flags: a Displacement holds what is not blank
assert beam_tab.support_flags({"mode": "disp", "ux": None, "uy": 0.0, "rz": 3.0}) == (False, True, True)
assert beam_tab.support_flags({"mode": "disp", "ux": 1.0, "uy": None, "rz": None}) == (True, False, False)
assert beam_tab.support_flags({"mode": "pinned"}) == (True, True, False)

# ----------------------------------------------------------------------------------------------------------------- the dialog, the table, the drawing
b, q = new_tab(); a, z = q
asked = []
orig = sim_disp.ask
sim_disp.ask = lambda parent, title, keys, units, current=None, note=sim_disp.NOTE: (asked.append((title, tuple(keys), dict(units))) or {"ux": None, "uy": 1.5, "rz": 0.0})
b.canvas.sel = []
b.add_displacement()
assert not b.supports and not asked and "Select one or more joints" in MSGS[-1]
b.canvas.sel = [("pt", z)]
b.add_displacement()
assert asked == [("Displacement", ("ux", "uy", "rz"), {"ux": "mm", "uy": "mm", "rz": "deg"})], asked
assert b.supports == [{"mode": "disp", "targets": [z], "ux": None, "uy": 1.5, "rz": 0.0}], b.supports
sim_disp.ask = lambda *a_, **k: {"ux": None, "uy": None, "rz": None}
b.add_displacement()
assert len(b.supports) == 1, "all blank: nothing added"
sim_disp.ask = orig
b.supports.append({"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": None})
b.refresh_lists()
tb = b.cond_table
rows = [[tb.item(r, c).text() for c in range(4)] for r in range(tb.rowCount())]
assert rows[0][0] == "Displacement 1" and rows[0][1] == "Displacement (ux, uy, rotation) (mm, mm, deg)" and rows[0][3] == "free, 1.5, 0", rows
assert rows[1][3] == "0, 0, free" and rows[1][0] == "Displacement 2", rows
# editing the value
assert b.set_condition_value(0, "free, 2, 5") and b.supports[0]["uy"] == 2.0 and b.supports[0]["rz"] == 5.0 and b.supports[0]["ux"] is None
assert b.set_condition_value(0, "1, , held") and b.supports[0]["ux"] == 1.0 and b.supports[0]["uy"] is None and b.supports[0]["rz"] == 0.0
assert not b.set_condition_value(0, "free, free, free") and b.supports[0]["ux"] == 1.0
assert not b.set_condition_value(0, "1, 2") and not b.set_condition_value(0, "a, b, c") and b.supports[0]["ux"] == 1.0
# the moves are what the solver is given: lengths as they are, the rotation in radians, nothing for a direction that is only held
b.supports = [{"mode": "disp", "targets": [z], "ux": None, "uy": 1.5, "rz": 90.0}, {"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": None}]
mv = b.support_moves()
assert set(mv) == {z} and mv[z][0] == 0.0 and mv[z][1] == 1.5 and abs(mv[z][2] - math.pi / 2) < 1e-12, mv
assert b.solver_opts()["moves"] == mv
# the canvas draws every kind of symbol without trouble, and different ones for different directions
import beam_canvas
from PyQt6.QtGui import QImage, QPainter, QColor
b.resize(900, 600); b.show(); app.processEvents(); b.canvas.fit()


def picture(sup):
    b.supports = [sup]
    img = QImage(b.canvas.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    with b.canvas.forced("supports"):
        b.canvas.paint_supports(p)
    p.end()
    return img


def inked(img):
    return sum(1 for y in range(0, img.height(), 1) for x in range(0, img.width(), 1) if img.pixelColor(x, y).alpha() and img.pixelColor(x, y) != QColor("white"))


kinds = {"fixed block": {"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": 0.0},
         "pin": {"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": None},
         "roller below": {"mode": "disp", "targets": [a], "ux": None, "uy": 0.0, "rz": None},
         "roller beside": {"mode": "disp", "targets": [a], "ux": 0.0, "uy": None, "rz": None},
         "turn lock": {"mode": "disp", "targets": [a], "ux": None, "uy": None, "rz": 0.0},
         "moved": {"mode": "disp", "targets": [a], "ux": None, "uy": 2.0, "rz": None},
         "turned": {"mode": "disp", "targets": [a], "ux": 0.0, "uy": 0.0, "rz": 10.0}}
ink = {k: inked(picture(v)) for k, v in kinds.items()}
assert all(v > 20 for v in ink.values()), ink
assert len(set(ink.values())) >= 6, ink
assert ink["moved"] > ink["roller below"], "a number draws an arrow on top of the roller"
assert ink["turned"] > ink["pin"], "a turn draws an arc on top of the pin"

# ----------------------------------------------------------------------------------------------------------------- units: lengths scale, the rotation (degrees) does not
b, q = new_tab(); a, z = q
b.supports = [{"mode": "disp", "targets": [z], "ux": None, "uy": 2.0, "rz": 5.0}, {"mode": "disp", "targets": [a], "ux": 0.0, "uy": None, "rz": None}]
st = pstore.convert_beam_state(b.export_state(), "Metric (mm, kg, N, s, MPa)", "Metric (m, kg, N, s, Pa)", True)
s0, s1 = st["supports"]
assert abs(s0["uy"] - 2e-3) < 1e-15 and s0["rz"] == 5.0 and s0["ux"] is None and s1["ux"] == 0.0 and s1["uy"] is None, (s0, s1)
back = pstore.convert_beam_state(st, "Metric (m, kg, N, s, Pa)", "Metric (mm, kg, N, s, MPa)", True)
assert abs(back["supports"][0]["uy"] - 2.0) < 1e-12 and back["supports"][0]["rz"] == 5.0
# the tab itself follows a change of the unit system
b.supports = [dict(FIXED, targets=[a]), {"mode": "disp", "targets": [z], "ux": None, "uy": 2.0, "rz": 5.0}]
b.change_units("Metric (mm, kg, N, s, MPa)", "Metric (m, kg, N, s, Pa)", True)
assert abs(b.supports[1]["uy"] - 2e-3) < 1e-15 and b.supports[1]["rz"] == 5.0 and b.supports[1]["ux"] is None, b.supports[1]
assert abs(b.support_moves()[z][1] - 2e-3) < 1e-15 and abs(b.support_moves()[z][2] - math.radians(5.0)) < 1e-15

# ----------------------------------------------------------------------------------------------------------------- a study can run it, with no load at all
b, q = new_tab(); a, z = q
b.supports = [FIXED | {"targets": [a]}, {"mode": "disp", "targets": [z], "ux": None, "uy": 1.0, "rz": None}]
b.loads = []
ad = b.study_adapter()
assert ad.ready() is None
sp = ad.prepare({}, {})
assert sp["error"] is None, sp["error"]
case = sp["run"](lambda *a_, **k: None, lambda: False)
assert case["status"] == "ok", case
o = ad.case_outputs(case, ["beam.umax", "beam.sup1.ry"])
assert abs(o["beam.umax"] - 1.0) < 1e-6 and close(o["beam.sup1.ry"], 3 * E * I * 1.0 / L ** 3, 1e-6), o

# ----------------------------------------------------------------------------------------------------------------- the solver by itself (no window): the first-principles numbers
nodes = {1: (0.0, 0.0), 2: (L, 0.0)}
mem = {"id": 1, "name": "m", "a": 1, "b": 2, "E": E, "A": A, "I": I, "c_top": 20.0, "c_bottom": 20.0, "rel_a": False, "rel_b": False, "mat": None,
       "sy": 250.0, "su": 400.0, "qg": (0.0, 0.0), "ql": (0.0, 0.0)}
r = beam1d.solve(nodes, [mem], {1: (True, True, True), 2: (False, True, False)}, {}, 41, {"moves": {2: (0.0, d, 0.0)}})
assert close(r["reactions"][2][1], 3 * E * I * d / L ** 3)
r0 = beam1d.solve(nodes, [mem], {1: (True, True, True), 2: (False, True, False)}, {}, 41, {})
assert abs(r0["reactions"][2][1]) < 1e-9, "no moves: held at zero, as before"
print("ok")
