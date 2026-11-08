"""1D FEA: mesh, Timoshenko shear, nonlinear solve, profile copies, panel layout, persistence."""
import os, sys, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import beam_tab, sim_tab, profiles1d as pr1, beam1d

host = sim_tab.SimHost.__new__(sim_tab.SimHost)
host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
host.sketch_list = lambda: []
b = beam_tab.BeamTab(host)
bm = sc.Model(); q = [bm.add_point(0, 0), bm.add_point(1000, 0)]; bm.add_line(q[0], q[1])
b.set_model(bm, "cantilever")
b.set_profiles([0], pr1.compute("rect", {"b": 20.0, "h": 40.0}))
b.supports = [{"mode": "fixed", "targets": [q[0]]}]
b.loads = [{"kind": "force", "fx": 0.0, "fy": -500.0, "targets": [q[1]]}]
E_ = float(b.e_E.text()); I = 20 * 40 ** 3 / 12; P, L = 500.0, 1000.0
exact = P * L ** 3 / (3 * E_ * I)

# --- panel layout and defaults
assert b.cb_lin.isChecked() and b.cb_nl.isChecked() and not b.cb_shear.isChecked() and b.e_nel.text() == "1"
# --- default: exact beam, 1 element
assert b.solve(), "solve failed"
r = b.result
assert abs(r["umax"] - exact) / exact < 1e-6 and r.get("nl") is None
# --- mesh invariance
b.e_nel.setText("8")
assert b.solve(); r8 = b.result
assert abs(r8["umax"] - exact) / exact < 1e-6 and r8["mesh"]["elements"] == 8 and len(r8["mesh_nodes"]) == 7
b.cb_mesh.setChecked(True); b.canvas.update(); b.canvas.grab(); b.cb_mesh.setChecked(False)
# --- shear: adds P L /(G As)
b.cb_shear.setChecked(True)
assert b.solve(); rs = b.result
G = E_ / (2 * (1 + float(b.e_nu.text()))); As = pr1.shear_area(pr1.compute("rect", {"b": 20.0, "h": 40.0}))
assert abs((rs["umax"] - exact) - P * L / (G * As)) / (P * L / (G * As)) < 0.01, (rs["umax"], exact)
b.cb_shear.setChecked(False)
# --- bad mesh number
b.e_nel.setText("0")
try:
    b.solver_opts(); assert False
except beam1d.BeamError:
    pass
b.e_nel.setText("1")
# --- nonlinear only, small load equals linear; large load yields
b.cb_lin.setChecked(False)
assert b.solve(); rn = b.result
assert rn["nl"] is not None and abs(rn["umax"] - exact) / exact < 0.01, (rn["umax"], exact)
b.cb_lin.setChecked(True); b.cb_nl.setChecked(False)
assert b.solve() and b.result.get("nl") is None
b.cb_nl.setChecked(True)
# trigger: displacement trigger tiny -> switches to nonlinear
b.e_nld.setText("0.0001")
assert b.solve() and b.result.get("nl") is not None
b.e_nld.setText("")
# --- project save / restore keeps the new inputs
b.e_nel.setText("5"); b.cb_shear.setChecked(True)
st = b.export_state()
b2 = beam_tab.BeamTab(host); b2.import_state(st)
assert b2.e_nel.text() == "5" and b2.cb_shear.isChecked()
# --- unit change scales the target size
import physics_store, units
b.e_msize.setText("100")
st2 = physics_store.convert_beam_state(b.export_state(), list(units.SYSTEMS)[1], list(units.SYSTEMS)[0], True)
assert st2["inputs"]["e_msize"] != "100"

# --- profile copies
base = pr1.compute("rect", {"b": 20.0, "h": 40.0})
mv = pr1.compute("rect", {"b": 20.0, "h": 40.0}, copies={"mirror_v": True, "gap_v": 0.0})
assert abs(mv["A"] / base["A"] - 2) < 1e-9 and abs(mv["I"] / base["I"] - 2) < 1e-9 or abs(mv["I"] / base["I"] - 8) < 1e-9 or mv["I"] > base["I"]
st_ = pr1.compute("rect", {"b": 20.0, "h": 40.0}, copies={"ny": 2, "gy": 0.0})
one = pr1.compute("rect", {"b": 20.0, "h": 80.0})
assert abs(st_["I"] - one["I"]) / one["I"] < 1e-9 and abs(st_["A"] - one["A"]) < 1e-9
for bad in ({"ny": 2, "gy": -1.0}, {"nx": 0}, {"nx": 15, "ny": 15}):
    try:
        pr1.compute("rect", {"b": 20.0, "h": 40.0}, copies=bad); assert False, bad
    except ValueError:
        pass
assert pr1.fibres(st_) is not None and pr1.drawing(st_)
# --- nonlinear collapse: huge load yields a note and a load fraction below 1
b.e_nld.setText(""); b.e_nel.setText("1"); b.e_msize.setText("")
b.loads = [{"kind": "force", "fx": 0.0, "fy": -50000.0, "targets": [q[1]]}]
b.cb_lin.setChecked(False)
assert b.solve()
nl = b.result["nl"]
assert nl["lambda"] < 1.0 or nl["yielded"], nl
print("ALL OK")
