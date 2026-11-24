"""The 2D Thermal tab: every material is set in Material and analysis (a table of the regions), and an edge can be set to Insulated.

  1. Geometry holds only the shape: no material box, no material name in the list of regions; Material and analysis has the table, the editor and 'Use for all'
  2. three regions side by side, a material each (steel / air / copper from the library): the series-conduction answer, and what the table and the editor show
  3. numbers typed in the boxes: the region's own values ('(custom values)'); a wrong entry is refused with a reason and the boxes go back; the library
     (add and delete) with a region using it
  4. a region switched off is greyed and is not in the problem; 'Use for all regions'
  5. saved and reopened (the pickle whitelist); a project saved before this change (one material of the tab plus a few overrides) gives the same answer
  6. a split edge keeps the materials; File > Units: a library material keeps its physical value, a region's typed numbers are re-read in a relabel
  7. parametric studies: the three numbers of every region, and the three boxes of the tab as 'every region' (old studies keep working)
  8. Insulated: the button, the table row, the same answer as a heat flux of zero, the hatch on the drawing, the note about the edges that have no condition,
     saving and unit changes, and the study adapter
"""
import copy
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
TH = os.path.join(HERE, "dev_addons", "thermal2d")
sys.path[:0] = [HERE, SIM, TH, os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

import sketcher_core as sc
import physics_store as pstore
import sim_tab
import unitctl
import thermal_fem as tfem
import thermal_mat as tmat
import thermal_tab as tt
import thermal_units as tu

MM = "Metric (mm, kg, N, s, MPa)"
INCH = "US (in, lbf, psi)"
T_ = tempfile.mkdtemp(prefix="opara_thr_")
STEEL, COPPER, AIR = "Structural steel (A36)", "Copper", "Air (still)"


def close(a, b, rel=1e-6, ab=0.0):
    return abs(a - b) <= rel * max(abs(a), abs(b)) + ab


def host():
    h = sim_tab.SimHost.__new__(sim_tab.SimHost)
    h.doc = None
    h.m = sim_tab._HostModel()
    h._restoring = False
    h.status = lambda t: None
    h.sim = None
    h.sketch_list = lambda: []
    return h


def run_now(tab, title, fn):
    try:
        return "ok", fn(lambda *a, **k: None, lambda: False)
    except (tt.pg.Cancelled, tt.pf.Cancelled):
        return "cancelled", None
    except (tt.pg.GeometryError, tt.pf.ModelError) as ex:
        QMessageBox.warning(tab, title, str(ex))
        return "user", str(ex)


def new_tab(unit=MM):
    unitctl.set_units(unit, notify=False, persist=False)
    t = tt.ThermalTab(host())
    t.run_task = lambda title, fn: run_now(t, title, fn)
    return t


def answer(*vals):
    tt.ask_values = lambda parent, title, note, labels, defaults: list(vals)


def add(t, fn, sel, *vals):
    t.canvas.sel = list(sel)
    answer(*vals)
    getattr(t, fn)()


def mesh_solve(t, h):
    t.e_h.setText(str(h))
    t.run_mesh()
    assert t.mesh is not None, MSGS
    t.run_solve()
    assert t.result is not None, MSGS
    return t.result


def flow(res, name):
    return next(f["Q"] for f in res["flows"] if f["name"] == name)


def typed(edit, text):
    """What typing into a box does (setText alone sends no 'edited' signal)."""
    edit.setText(text)
    edit.textEdited.emit(text)


def strip():
    """Three regions side by side, 40 + 30 + 30 long and 20 high: lines 0..2 bottom, 3 right, 4..6 top, 7 left, 8 and 9 the walls between them."""
    m = sc.Model()
    xs = (0, 40, 70, 100)
    pb = [m.add_point(x, 0) for x in xs]
    pt_ = [m.add_point(x, 20) for x in xs]
    ls = [m.add_line(pb[i], pb[i + 1]) for i in range(3)] + [m.add_line(pb[3], pt_[3])] + [m.add_line(pt_[3 - i], pt_[2 - i]) for i in range(3)]
    ls += [m.add_line(pt_[0], pb[0]), m.add_line(pb[1], pt_[1]), m.add_line(pb[2], pt_[2])]
    return m, ls


def faces_by_x(t):
    """The region ids from the left one to the right one."""
    return [f["id"] for f in sorted(t.geom["faces"], key=lambda f: f["centroid"][0])]


def pick_row(t, fid, material=None):
    row = next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fid)
    t.mat_table.setCurrentCell(row, 0)
    if material is not None:
        t.mat_combo.setCurrentIndex(t.mat_combo.findData(material))
    return row


A = 0.020 * 0.001                            # the cross-section in m2: 20 mm high, 1 mm deep (the lengths in the sums below are in m)

# ================================================================================================================ 1. Geometry holds only the shape
t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
assert len(t.geom["faces"]) == 3 and t.mat_table.rowCount() == 3
assert not hasattr(t, "reg_mat_combo"), "no material box in Geometry"
assert all(tmat.DEFAULT not in t.regions.item(i).text() for i in range(3)), [t.regions.item(i).text() for i in range(3)]
combos = {w for w in t.reg_box.findChildren(type(t.mat_combo))}
assert not combos, "the box of the selected region in Geometry has no combo (its only entry is the heat generation)"
assert [t.mat_table.horizontalHeaderItem(c).text() for c in range(2)] == ["Region", "Material"]
assert all(t.mat_table.item(r, 1).text() == tmat.DEFAULT for r in range(3)) and t.mat_table.currentRow() == 0, "a first region is selected from the start"
assert t.mat_combo.isEnabled() and t.e_k.isEnabled() and t.b_all_mats.isEnabled() and "Region 1" in t.mat_sel_lbl.text()
empty = new_tab()
assert empty.mat_table.rowCount() == 0 and not empty.mat_combo.isEnabled() and not empty.e_k.isEnabled() and "Import a sketch" in empty.mat_sel_lbl.text()
print("1 ok: Geometry holds no material")

# ================================================================================================================ 2. three regions, a material each
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fl, STEEL)
pick_row(t, fm, AIR)
pick_row(t, fr_, COPPER)
assert [t.region_mats[f]["name"] for f in (fl, fm, fr_)] == [STEEL, AIR, COPPER]
assert [t.mat_table.item(next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == i), 1).text() for i in (fl, fm, fr_)] == [STEEL, AIR, COPPER]
assert t.materials_summary() == "3 materials" and "3 materials" in t.sections[1].summary()
setup = t.read_setup(need_mesh=False)
assert setup["region_mats"] == {fl: {"k": 51.9, "rho": 7850.0, "cp": 486.0}, fm: {"k": 0.026, "rho": 1.18, "cp": 1005.0}, fr_: {"k": 401.0, "rho": 8960.0, "cp": 385.0}}
t.e_t.setText("1")
add(t, "add_temperature", [("ln", ls[7])], 100.0)                       # the left end
add(t, "add_temperature", [("ln", ls[3])], 20.0)                        # the right end
r = mesh_solve(t, 4)
R = 0.040 / (51.9 * A) + 0.030 / (0.026 * A) + 0.030 / (401.0 * A)
assert close(flow(r, "Temperature 1"), 80.0 / R, 1e-4), (flow(r, "Temperature 1"), 80.0 / R)
assert set(np.round(np.unique(r["k_el"]), 6)) == {51.9, 0.026, 401.0}, "each region's conductivity reached its elements"
# the editor follows the selected region
pick_row(t, fm)
assert t.mat_combo.currentData() == AIR and close(float(t.e_k.text()), 0.026) and close(float(t.e_rho.text()), 1.18) and "Region 2" in t.mat_sel_lbl.text()
pick_row(t, fl)
assert t.mat_combo.currentData() == STEEL and close(float(t.e_k.text()), 51.9)
assert t.canvas.hl_face == next(r_ for r_, f in enumerate(t.geom["faces"]) if f["id"] == fl), "the selected region is shown on the drawing"
# changing a material clears the result that no longer matches; the library's name carries a note about its numbers
assert "Typical room-temperature" in t.mat_note.text()
pick_row(t, fl, COPPER)
assert t.result is None
# choosing "(custom values)" in the combo keeps the numbers the region has (they become its own); re-typing the same numbers of a library material changes nothing
pick_row(t, fl, COPPER)
t.mat_combo.setCurrentIndex(0)
assert t.region_mats[fl] == {"name": tt.CUSTOM, "k": 401.0, "rho": 8960.0, "cp": 385.0}, t.region_mats[fl]
assert t.mat_combo.currentData() is None and t.mat_table.item(next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fl), 1).text() == tt.CUSTOM
pick_row(t, fl, COPPER)
sig_c = t.signature_extra()
typed(t.e_k, "401")
typed(t.e_k, "401.0000000001")
assert t.region_mats[fl]["name"] == COPPER and t.signature_extra() == sig_c and t.mat_combo.currentData() == COPPER, "the same numbers again: still the library material"
typed(t.e_k, "400")
assert t.region_mats[fl] == {"name": tt.CUSTOM, "k": 400.0, "rho": 8960.0, "cp": 385.0}
print("2 ok: a material for each region")

# ================================================================================================================ 3. typed numbers, wrong entries, the library
t = new_tab()
t.set_model(*strip()[:1], "strip")
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fm)
sig0 = t.signature_extra()                                                # what marks the project as changed
typed(t.e_k, "12.5")
assert t.signature_extra() != sig0, "typed numbers change the project"
assert t.region_mats[fm] == {"name": tt.CUSTOM, "k": 12.5, "rho": 2700.0, "cp": 896.0}, t.region_mats[fm]
assert t.mat_combo.currentData() is None and t.mat_combo.currentText() == tt.CUSTOM
assert t.region_mats[fl]["name"] == tmat.DEFAULT, "the other regions did not change"
assert t.mat_table.item(next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fm), 1).text() == tt.CUSTOM
assert "Typical room-temperature" not in t.mat_note.text()
sig1 = t.signature_extra()
typed(t.e_rho, "1234")
typed(t.e_cp, "321")
assert t.region_mats[fm] == {"name": tt.CUSTOM, "k": 12.5, "rho": 1234.0, "cp": 321.0} and t.signature_extra() != sig1
# a half-typed or wrong entry: nothing is written, Solve says why, and leaving the box puts the real numbers back
typed(t.e_k, "")
assert t.region_mats[fm]["k"] == 12.5 and t._box_error is not None
try:
    t.read_setup(need_mesh=False)
    raise AssertionError("a wrong entry in the boxes must stop the solve")
except tt.pf.ModelError as ex:
    assert "conductivity" in str(ex)
t.e_k.editingFinished.emit()
assert close(float(t.e_k.text()), 12.5) and t._box_error is None and "kept its material" in t.status_lbl.text() and "conductivity" in t.status_lbl.text()
typed(t.e_cp, "-3")
assert t.region_mats[fm]["cp"] == 321.0 and "greater than zero" in t._box_error
t.e_cp.editingFinished.emit()
assert close(float(t.e_cp.text()), 321.0)
typed(t.e_rho, "abc")
assert t._box_error and t.region_mats[fm]["rho"] == 1234.0
pick_row(t, fl)                                                           # going to another region drops the half-typed entry
assert t._box_error is None and close(float(t.e_k.text()), 167.0)
# the library: your own material, used by a region, then deleted: the region keeps its numbers
import PyQt6.QtWidgets as QW
QW.QInputDialog.getText = staticmethod(lambda *a, **k: ("My ceramic", True))
pick_row(t, fm)
t.add_material()
assert t.region_mats[fm] == {"name": "My ceramic", "k": 12.5, "rho": 1234.0, "cp": 321.0} and t.mat_combo.currentData() == "My ceramic"
assert t.mat_table.item(next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fm), 1).text() == "My ceramic" and t.b_del_mat.isEnabled()
pick_row(t, fr_, "My ceramic")
assert t.region_mats[fr_]["k"] == 12.5
t.delete_material()
assert tmat.find("My ceramic") is None and t.region_mats[fm] == {"name": tt.CUSTOM, "k": 12.5, "rho": 1234.0, "cp": 321.0} and t.region_mats[fr_]["name"] == tt.CUSTOM
assert not t.b_del_mat.isEnabled()
# 'Add material' with a wrong number is refused before asking for a name
typed(t.e_k, "0")
n_msg = len(MSGS)
t.add_material()
assert len(MSGS) == n_msg + 1 and "greater than zero" in MSGS[-1]
# a region of a slice whose part has no thermal values carries the default material, marked; typing its numbers is choosing a material too
ts = new_tab()
ts.set_model(*strip()[:1], "slice")
a_, b_, c_ = faces_by_x(ts)
ts.sim_apply_regions({a_: 0, b_: 1, c_: 2}, {a_: "Sink", b_: "Chip", c_: "Pad"}, {a_: {"name": "Copper"}, b_: {"name": "Mystery"}, c_: {"name": "Unobtainium"}})
ts.fill_regions()
assert ts.unset_regions == {b_, c_} and ts.region_mats[b_]["name"] == tmat.DEFAULT and ts.region_mats[a_]["name"] == "Copper"
pick_row(ts, b_)
typed(ts.e_k, "33")
assert ts.unset_regions == {c_} and "choose" not in ts.mat_table.item(next(r for r, f in enumerate(ts.geom["faces"]) if f["id"] == b_), 1).text()
pick_row(ts, c_)
assert ts.mat_table.item(next(r for r, f in enumerate(ts.geom["faces"]) if f["id"] == c_), 1).foreground().color().name() == "#b3261e"
ts.material_for_all()
assert ts.unset_regions == set()
print("3 ok: typed numbers, wrong entries, the library")

# ================================================================================================================ 4. a region that is switched off; 'Use for all regions'
t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fl, STEEL)
pick_row(t, fm, AIR)
rm = next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fm)
assert t.mat_table.currentRow() == rm
t.regions.item(rm).setCheckState(tt.Qt.CheckState.Unchecked)
outer = [ls[0], ls[2], ls[3], ls[4], ls[6], ls[7]]                         # the middle region's own top and bottom are no longer edges of the model, its two walls are
assert t.boundary_edges() == {("ln", x) for x in outer + ls[8:10]}, t.boundary_edges()
assert t.cond_note.text() == "8 edges of the model have no condition and are insulated (no heat through them): " + t.names(t.uncovered_edges()[:6]) + " and 2 more."
assert t.mat_table.currentRow() == rm, "the table keeps its selection when a region is switched off"
assert t.geom["faces"][rm]["included"] is False
assert t.mat_table.item(rm, 1).foreground().color().name() == "#8a8a8a" and "switched off" in t.mat_table.item(rm, 1).toolTip()
assert fm not in t.read_setup(need_mesh=False)["region_mats"] and fl in t.read_setup(need_mesh=False)["region_mats"]
assert t.mat_combo.isEnabled()
t.regions.item(rm).setCheckState(tt.Qt.CheckState.Checked)
pick_row(t, fl)
t.material_for_all()
assert all(t.region_mats[f] == {"name": STEEL, "k": 51.9, "rho": 7850.0, "cp": 486.0} for f in (fl, fm, fr_)) and "Every region now has" in t.status_lbl.text()
assert t.materials_summary() == STEEL and t.mat_table.currentRow() == next(r for r, f in enumerate(t.geom["faces"]) if f["id"] == fl)
print("4 ok: switched-off region, use for all")

# ================================================================================================================ 5. saved and reopened; a project saved before this change
t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fl, STEEL)
pick_row(t, fm)
typed(t.e_k, "7.5")
pick_row(t, fr_, COPPER)
t.e_t.setText("1")
add(t, "add_temperature", [("ln", ls[7])], 100.0)
add(t, "add_temperature", [("ln", ls[3])], 20.0)
mesh_solve(t, 4)
f5 = os.path.join(T_, "regions.sim")
assert pstore.save(f5, {"main": t}) == ["main"]
st = pstore.load(f5)["main"]
assert st["region_mats_all"] is True
t2 = new_tab()
t2.import_state(st)
assert t2.region_mats == t.region_mats and [t2.mat_table.item(r, 1).text() for r in range(3)] == [t.mat_table.item(r, 1).text() for r in range(3)]
assert t2.read_setup() == t.read_setup(), "the same problem comes back"
pick_row(t2, fm)
assert t2.mat_combo.currentData() is None and close(float(t2.e_k.text()), 7.5), "the editor shows the custom region"
t2.run_solve()
assert np.allclose(t2.result["T"], t.result["T"], rtol=0, atol=1e-9)

# a project from before: the main material of the tab (name + boxes) and a few regions with their own
old = copy.deepcopy(t.export_state())
old.pop("region_mats_all")
old["region_mats"] = {fm: {"name": "Copper", "k": 401.0, "rho": 8960.0, "cp": 385.0}}
old["material"] = "Brass (cartridge)"
old["inputs"]["e_k"], old["inputs"]["e_rho"], old["inputs"]["e_cp"] = "120", "8530", "380"
t3 = new_tab()
t3.import_state(old)
BRASS = {"name": "Brass (cartridge)", "k": 120.0, "rho": 8530.0, "cp": 380.0}
assert t3.region_mats == {fl: BRASS, fm: {"name": "Copper", "k": 401.0, "rho": 8960.0, "cp": 385.0}, fr_: BRASS}, t3.region_mats
legacy = t3.read_setup()
legacy["mat"] = {"k": 120.0, "rho": 8530.0, "cp": 380.0}                                   # what the old tab handed to the solver: the main material ...
legacy["region_mats"] = {fm: {"k": 401.0, "rho": 8960.0, "cp": 385.0}}                      # ... and the overrides
assert np.array_equal(tfem.solve(t3.mesh, legacy)["T"], tfem.solve(t3.mesh, t3.read_setup())["T"]), "an old project gives the answer it gave"
# an old project whose boxes hold numbers that are not a material of the library
old2 = copy.deepcopy(old)
old2["material"] = None
old2["inputs"]["e_k"] = "77"
t4 = new_tab()
t4.import_state(old2)
assert t4.region_mats[fl] == {"name": tt.CUSTOM, "k": 77.0, "rho": 8530.0, "cp": 380.0} and t4.region_mats[fm]["name"] == "Copper"
# an old project with unreadable boxes: the default material, not a crash
old3 = copy.deepcopy(old)
old3["inputs"]["e_k"] = "oops"
t5 = new_tab()
t5.import_state(old3)
assert t5.region_mats[fl]["name"] == tmat.DEFAULT and t5.region_mats[fm]["name"] == "Copper"
print("5 ok: saved and reopened, an old project")

# ================================================================================================================ 6. a split keeps the materials; units
t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fl, STEEL)
pick_row(t, fm)
typed(t.e_k, "7.5")
pick_row(t, fr_, COPPER)
def by_x(tab):
    """The materials from the left region to the right one (a split moves a region's centroid a little, so they are not keyed by it)."""
    return [dict(tab.region_mats[f["id"]]) for f in sorted(tab.geom["faces"], key=lambda f: f["centroid"][0])]


before = by_x(t)
t.apply_split(("ln", ls[4]), 12.0)
assert by_x(t) == before and len(t.geom["faces"]) == 3 and t.mat_table.rowCount() == 3 and len(t.region_mats) == 3
assert all(t.mat_table.item(r, 1).text() == t.region_mats[t.geom["faces"][r]["id"]]["name"] for r in range(3))
# File > Units: converted (the physical values stay) ...
unitctl.set_units(INCH, notify=False, persist=False)
t.change_units(MM, INCH, True)
assert by_x(t) == before, "converting the unit system leaves the materials (SI) as they are"
pick_row(t, fl)
assert t.mat_combo.currentData() == STEEL and close(float(t.e_k.text()), 51.9 / 1.730734666, 1e-8) and "Btu" in t.lbl_k.text()
assert sorted(m_["name"] for m_ in t.region_mats.values()) == sorted([STEEL, COPPER, tt.CUSTOM]) and sorted(m_["k"] for m_ in t.region_mats.values()) == [7.5, 51.9, 401.0]
# ... or only relabelled: the library keeps its physical value, the typed numbers are read in the new unit
unitctl.set_units(MM, notify=False, persist=False)
t.change_units(INCH, MM, True)
unitctl.set_units(INCH, notify=False, persist=False)
t.change_units(MM, INCH, False)
fm_ = next(f for f in t.geom["faces"] if t.region_mats[f["id"]]["name"] == tt.CUSTOM)["id"]
fam = tu.family_of(INCH)
assert close(t.region_mats[fm_]["k"], fam.to_si("k", 7.5), 1e-9) and close(t.region_mats[fm_]["rho"], fam.to_si("rho", 2700.0), 1e-9), t.region_mats[fm_]
assert any(m_["name"] == STEEL and m_["k"] == 51.9 for m_ in t.region_mats.values()), "a library material keeps its physical value"
unitctl.set_units(MM, notify=False, persist=False)
print("6 ok: split and units")

# ================================================================================================================ 7. parametric studies
import study_iface as si
t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
fl, fm, fr_ = faces_by_x(t)
pick_row(t, fl, STEEL)
pick_row(t, fm, STEEL)
pick_row(t, fr_, STEEL)
t.e_t.setText("1")
add(t, "add_temperature", [("ln", ls[7])], 100.0)
add(t, "add_temperature", [("ln", ls[3])], 20.0)
t.e_h.setText("4")
ad = t.study_adapter()
ps = {d["id"]: d for d in ad.params()}
for f, nm in ((fl, "Region 1"), (fm, "Region 2"), (fr_, "Region 3")):
    for key, lab in (("k", "conductivity"), ("rho", "density"), ("cp", "specific heat")):
        d = ps[f"thermal.mat{f}.{key}"]
        assert d["label"].startswith(f"{nm}: {lab}") and d["group"] == "Thermal material values", d
assert ps[f"thermal.mat{fm}.k"]["now"] == "51.9" and ps[f"thermal.mat{fm}.k"]["label"].endswith("(W/(m K))")
assert ps["thermal.e_k"]["label"] == "Conductivity (every region)"
ctx = {}


def run_case(values):
    spec = ad.prepare(values, ctx)
    assert spec["error"] is None, spec["error"]
    case = spec["run"](lambda *a, **k: None, lambda: False)
    assert case["status"].startswith("ok"), case
    return case


def heat(case):
    return ad.case_outputs(case, ["thermal.flow0"])["thermal.flow0"]


Rs = lambda k1, k2, k3: 0.040 / (k1 * A) + 0.030 / (k2 * A) + 0.030 / (k3 * A)
assert close(heat(run_case({})), 80.0 / Rs(51.9, 51.9, 51.9), 1e-4)
assert close(heat(run_case({f"thermal.mat{fm}.k": "0.026"})), 80.0 / Rs(51.9, 0.026, 51.9), 1e-4), "one region's conductivity"
assert close(heat(run_case({"thermal.e_k": "401"})), 80.0 / Rs(401.0, 401.0, 401.0), 1e-4), "the box of the tab stands for every region (an old study)"
assert close(heat(run_case({"thermal.e_k": "401", f"thermal.mat{fr_}.k": "10"})), 80.0 / Rs(401.0, 401.0, 10.0), 1e-4), "a region's own value wins"
# the density and the specific heat of a region matter in a transient run: more heat capacity in the region next to the hot end, a colder plate at the end time
tr = {"thermal.analysis_combo": "Transient (changes with time)", "thermal.e_T0": "20", "thermal.e_tend": "20", "thermal.e_steps": "40"}
c_ref = run_case(dict(tr))
c_rho = run_case(dict(tr, **{f"thermal.mat{fl}.rho": str(7850.0 * 10)}))
c_cp = run_case(dict(tr, **{f"thermal.mat{fl}.cp": str(486.0 * 10)}))
assert c_rho["result"]["Tmean"] < c_ref["result"]["Tmean"] - 0.05 and c_cp["result"]["Tmean"] < c_ref["result"]["Tmean"] - 0.05
assert np.allclose(c_rho["result"]["T"], c_cp["result"]["T"], rtol=0, atol=1e-9), "ten times the density or ten times the specific heat: the same heat capacity"
c_same = run_case(dict(tr, **{f"thermal.mat{fl}.rho": "7850", f"thermal.mat{fl}.cp": "486"}))
assert np.array_equal(c_same["result"]["T"], c_ref["result"]["T"]), "the values it already had change nothing"
assert t.region_mats[fl]["k"] == 51.9 and t.region_mats[fm]["k"] == 51.9 and t.region_mats[fr_]["k"] == 51.9, "a study never touches the tab on screen"
spec = ad.prepare({f"thermal.mat{fm}.k": "-1"}, ctx)
res = spec["run"](lambda *a, **k: None, lambda: False) if spec["error"] is None else {"status": "failed"}
assert res["status"] == "failed" or spec["error"], "a conductivity of zero or less is reported, not solved"
print("7 ok: studies")

# ================================================================================================================ 8. Insulated
def hatch_points(tab):
    """The pixels of the drawing that have the colour of the insulation hatch (#5b6770, within a few levels), as (x, y) screen points."""
    tab.canvas.resize(700, 420)
    tab.canvas.fit()
    tags, tab.canvas.tag_list = tab.canvas.tag_list, ()          # the lettered tags (an insulated one is the same grey as the hatch) are not what is counted
    try:
        img = tab.canvas.grab().toImage()
    finally:
        tab.canvas.tag_list = tags
    ref, pts = QColor("#5b6770"), []
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - ref.red()) < 6 and abs(c.green() - ref.green()) < 6 and abs(c.blue() - ref.blue()) < 6:
                pts.append((x, y))
    return pts


def hatch_pixels(tab):
    return len(hatch_points(tab))


t = new_tab()
m, ls = strip()
t.set_model(m, "strip")
t.e_t.setText("1")
bottom, top, left_, right_, walls = ls[0:3], ls[4:7], ls[7], ls[3], ls[8:10]
btn = next(b for b in t.findChildren(QPushButton) if b.text().strip() == "Insulated")
assert not btn.icon().isNull() and "adiabatic" in btn.toolTip() and "free to change" in btn.toolTip()
# the note: how many edges of the model have no condition (they are insulated); the two walls between the regions are inside the material
assert t.boundary_edges() == {("ln", x) for x in bottom + top + [left_, right_]}
assert t.uncovered_edges() == sorted(("ln", x) for x in bottom + top + [left_, right_])
assert t.cond_note.text() == "8 edges of the model have no condition and are insulated (no heat through them): " + t.names(t.uncovered_edges()[:6]) + " and 2 more.", t.cond_note.text()
add(t, "add_temperature", [("ln", left_)], 100.0)
add(t, "add_temperature", [("ln", right_)], 20.0)
assert t.uncovered_edges() == sorted(("ln", x) for x in bottom + top)
assert t.cond_note.text() == "6 edges of the model have no condition and are insulated (no heat through them): " + t.names(t.uncovered_edges()) + ".", t.cond_note.text()
t.outline.select("Conditions"); app.processEvents()                     # the drawing shows the conditions only under their node
n0 = hatch_pixels(t)
assert n0 == 0, "no hatch on the drawing before an edge is set to Insulated"
t.canvas.sel = [("ln", x) for x in bottom]
t.add_insulated()
assert t.loads == [{"kind": "ins", "targets": [("ln", x) for x in bottom]}]
row = t.cond_table.rowCount() - 1
assert t.cond_table.item(row, 0).text() == "Insulated 1" and "no heat through the edge" in t.cond_table.item(row, 1).text()
assert t.cond_table.item(row, 2).text() == t.names(t.loads[0]["targets"]) and t.cond_table.item(row, 3).text() == ""
assert not (t.cond_table.item(row, 3).flags() & tt.Qt.ItemFlag.ItemIsEditable) and (t.cond_table.item(row, 0).flags() & tt.Qt.ItemFlag.ItemIsEditable)
assert t.set_condition_value(row, "5") is False and t.loads[0] == {"kind": "ins", "targets": [("ln", x) for x in bottom]}
assert t.uncovered_edges() == sorted(("ln", x) for x in top) and t.cond_note.text().startswith("3 edges of the model have no condition")
assert hatch_pixels(t) > 100, "the insulated edges are hatched on the drawing"
# the shape of the hatch: short slanted ticks that start on the edge and end 8 pixels outside the body (below the bottom edges); not arrows, not inside
edge_pts = {e["src"]: pp for e, pp in zip(t.geom["edges"], t.geom["polys"])}
y_bottom = t.canvas.w2s(0, 0).y()
for k in bottom:
    ticks = t.canvas.insulation_ticks(edge_pts[("ln", k)], False)
    assert len(ticks) >= 3
    for a, b in ticks:
        assert abs(a.y() - y_bottom) < 1e-6 and abs((b.y() - a.y()) - 8.0) < 1e-6, "a tick starts on the edge and ends 8 pixels outside the body"
        assert abs(abs(b.x() - a.x()) - 6.0) < 1e-6, "and is slanted along the edge"
hp = hatch_points(t)
ys = [y for _x, y in hp]
assert min(ys) >= y_bottom - 2 and max(ys) <= y_bottom + 11, (min(ys), max(ys), y_bottom)
x_lo, x_hi = t.canvas.w2s(0, 0).x(), t.canvas.w2s(100, 0).x()
assert all(x_lo - 8 <= x <= x_hi + 8 for x, _y in hp) and len({y for y in ys}) >= 6, "the hatch hugs the insulated edges"
t.cond_table.setCurrentCell(row, 0)
assert t.edit_condition() is True                                         # a row without a value lets you rename it
t.rename_condition(row, "Bottom wall")
assert t.cond_table.item(row, 0).text() == "Bottom wall" and t.loads[0]["name"] == "Bottom wall"
t.canvas.sel = []
n_msg = len(MSGS)
t.add_insulated()                                                         # nothing selected: said, nothing added
assert len(t.loads) == 1 and len(MSGS) == n_msg + 1 and "Select" in MSGS[-1]
t.canvas.sel = [("pt", 0)]
t.add_insulated()                                                         # a point is not an edge
assert len(t.loads) == 1
t.canvas.sel = [("ln", x) for x in top[:2]]
t.add_insulated()
assert t.loads[1] == {"kind": "ins", "targets": [("ln", x) for x in top[:2]]} and t.cond_table.item(row + 1, 0).text() == "Insulated 2"
assert t.cond_note.text() == f"1 edge of the model has no condition and is insulated (no heat through it): Line {top[2]}.", t.cond_note.text()
t.canvas.sel = [("ln", top[2])]
t.add_insulated()
assert t.loads[2] == {"kind": "ins", "targets": [("ln", top[2])]} and t.cond_table.item(row + 2, 0).text() == "Insulated 3"
assert t.uncovered_edges() == [] and t.cond_note.text() == "Every edge of the model has a condition."
print("8a ok: the Insulated button, its row, the hatch and the note")

# the answer: the same as with no condition on those edges, and as a heat flux of zero; it adds nothing to the heat flows
for fid, name in zip(faces_by_x(t), (STEEL, AIR, COPPER)):
    pick_row(t, fid, name)
r_ins = mesh_solve(t, 4)
R = 0.040 / (51.9 * A) + 0.030 / (0.026 * A) + 0.030 / (401.0 * A)
assert close(flow(r_ins, "Temperature 1"), 80.0 / R, 1e-4)
assert flow(r_ins, "Bottom wall") == 0.0 and flow(r_ins, "Insulated 2") == 0.0 and flow(r_ins, "Insulated 3") == 0.0 and r_ins["balance"]["relative_error"] < 1e-8
setup = t.read_setup()
assert [c["kind"] for c in setup["conds"]] == ["temp", "temp", "ins", "ins", "ins"] and setup["conds"][2]["name"] == "Bottom wall"
bare = dict(setup, conds=[c for c in setup["conds"] if c["kind"] != "ins"])
zero = dict(setup, conds=[c if c["kind"] != "ins" else dict(c, kind="flux", q=0.0) for c in setup["conds"]])
assert np.array_equal(tfem.solve(t.mesh, bare)["T"], r_ins["T"]), "an edge with no condition is insulated: the same temperatures"
assert np.array_equal(tfem.solve(t.mesh, zero)["T"], r_ins["T"]), "and so is a heat flux of zero"
# a temperature and 'Insulated' on the same edge: the temperature holds (insulated adds nothing)
both = dict(setup, conds=setup["conds"] + [{"kind": "ins", "name": "x", "targets": [("ln", left_)]}])
assert np.array_equal(tfem.solve(t.mesh, both)["T"], r_ins["T"])
add(t, "add_conv", [("ln", walls[0])], 40.0, 20.0)                      # a convection on an inner wall: it is only here to have a condition with a number after the insulated ones
print("8b ok: the answer")

# diagnostics, saving, unit changes
txt = t.diagnostics_text()
assert "Bottom wall: ins" in txt and "Insulated 2: ins" in txt and "Insulated 3: ins" in txt
f8 = os.path.join(T_, "ins.sim")
assert pstore.save(f8, {"main": t}) == ["main"]
t2 = new_tab()
t2.import_state(pstore.load(f8)["main"])
assert t2.loads == t.loads and t2.read_setup() == t.read_setup() and t2.cond_note.text() == t.cond_note.text()
assert t2.cond_table.item(row, 0).text() == "Bottom wall" and t2.cond_table.item(row, 3).text() == ""
unitctl.set_units(INCH, notify=False, persist=False)
t2.change_units(MM, INCH, True)
assert [x["kind"] for x in t2.loads] == ["ins", "ins", "ins", "conv"] and t2.loads[0]["targets"] == t.loads[0]["targets"] and t2.cond_table.item(row, 3).text() == ""
t2.change_units(INCH, MM, False)                                          # a relabel: the conditions with numbers are re-read, 'Insulated' has none
assert [x["kind"] for x in t2.loads] == ["ins", "ins", "ins", "conv"] and t2.loads[0] == {"kind": "ins", "targets": t.loads[0]["targets"], "name": "Bottom wall"}
unitctl.set_units(MM, notify=False, persist=False)
print("8c ok: diagnostics, saving, units")

# the study adapter: nothing to vary on an insulated edge, but the heat through it is an output (0)
ad = t.study_adapter()
ps = ad.params()
assert not any("ins" in d["id"] for d in ps) and not any(d["label"].startswith("Bottom wall") for d in ps)
assert any(d["id"] == "thermal.load3.h" for d in ps), "the convection after the three insulated ones is load3"
outs = {o["id"]: o["label"] for o in ad.outputs()}
assert "Bottom wall" in outs["thermal.flow2"] and "Insulated 2" in outs["thermal.flow3"] and "Insulated 3" in outs["thermal.flow4"], outs
spec = ad.prepare({"thermal.load3.h": "80"}, {})
assert spec["error"] is None
case = spec["run"](lambda *a, **k: None, lambda: False)
assert case["status"].startswith("ok") and ad.case_outputs(case, ["thermal.flow2", "thermal.flow3", "thermal.flow4"]) == {"thermal.flow2": 0.0, "thermal.flow3": 0.0, "thermal.flow4": 0.0}
print("8d ok: studies")
print("OK thermal regions and insulated edges")
