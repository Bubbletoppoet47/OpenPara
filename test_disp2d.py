"""The Displacement support of the 2D FEA window: blank = free, 0 = held, a number = imposed.
Known answers: a bar moved at one end by an imposed displacement carries the stress E * delta / L (plane stress, free sides) and the support reacts with E * delta / L * h * t;
the same bar loaded by that force (pressure on the end) moves by exactly delta; the nonlinear solver gives the same answer while the bar stays elastic.
Old files: 'ux = 0' / 'uy = 0' supports open as a Displacement with that direction at 0 and the other blank; the buttons, the table, the unit change."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
import numpy as np
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import sketcher_core as sc
import physics_tab, sim_tab, sim_disp
import physics_fea as pf

W, H = 100.0, 20.0
E, NU, TH = 200000.0, 0.26, 1.0


def rect(w=W, h=H):
    m = sc.Model()
    p = [m.add_point(*c) for c in ((0, 0), (w, 0), (w, h), (0, h))]
    ls = [m.add_line(p[i], p[(i + 1) % 4]) for i in range(4)]
    return m, p, ls


def new_tab():
    host = sim_tab.SimHost.__new__(sim_tab.SimHost)
    host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t: None; host.sim = None
    host.sketch_list = lambda: []
    t = physics_tab.PhysicsTab(host)
    m, p, ls = rect()
    t.set_model(m, "rect")
    t.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
    t.e_h.setText("5")
    t.run_mesh()
    return t, p, ls


def solve(t, sup, loads):
    mat = t.read_material()
    return pf.solve(t.mesh, mat, [dict(s) for s in sup], [dict(l) for l in loads])


def edge_nodes(res, x):
    nd = np.asarray(res["mesh"]["nodes"])                      # the corner nodes and the mid-side nodes of the quadratic elements
    return np.where(np.abs(nd[:, 0] - x) < 1e-6)[0]


# ----------------------------------------------------------------------------------------------------------------- the parser and the helpers
assert sim_disp.parse("") is None and sim_disp.parse("free") is None and sim_disp.parse("held") == 0.0 and sim_disp.parse("0") == 0.0
assert sim_disp.parse("1,5") == 1.5 and sim_disp.parse(" -2 ") == -2.0
try:
    sim_disp.parse("abc"); assert False
except ValueError:
    pass
assert sim_disp.check({"ux": None, "uy": None}, ("ux", "uy")) and sim_disp.check({"ux": 0.0, "uy": None}, ("ux", "uy")) is None
assert sim_disp.upgrade({"mode": "x", "targets": [1]}, 2) == {"mode": "disp", "ux": 0.0, "uy": None, "targets": [1]}
assert sim_disp.upgrade({"mode": "y", "targets": [1]}, 2) == {"mode": "disp", "ux": None, "uy": 0.0, "targets": [1]}
assert sim_disp.upgrade({"mode": "fixed", "targets": [1]}, 2)["mode"] == "fixed"
assert sim_disp.has_imposed([{"mode": "disp", "ux": 0.1, "uy": None}]) and not sim_disp.has_imposed([{"mode": "disp", "ux": 0.0, "uy": None}])

# ----------------------------------------------------------------------------------------------------------------- the bar with an imposed end displacement
t, p, ls = new_tab()
delta = 0.05
left, right, bottom = ("ln", ls[3]), ("ln", ls[1]), ("ln", ls[0])
sup = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [left]},               # the left end cannot move along x, it is free to slide in y ...
       {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", p[0])]},        # ... but the bottom-left corner stops the bar from sliding away
       {"mode": "disp", "ux": delta, "uy": None, "targets": [right]}]             # the right end is pulled by exactly delta
res = solve(t, sup, [])                                                       # no load at all: the displacement is the load
u = res["u"]
xr, xl = edge_nodes(res, W), edge_nodes(res, 0.0)
assert np.allclose(u[xr, 0], delta, atol=1e-12), u[xr, 0]
assert np.allclose(u[xl, 0], 0.0, atol=1e-12)
nd = np.asarray(res["mesh"]["nodes"])
assert np.allclose(u[:, 0], delta * nd[:, 0] / W, atol=1e-9), "the displacement of a bar pulled at one end grows linearly with x"
R = res["reaction_on_body"]
force = E * delta / W * H * TH                                                # sigma * area
assert abs(R[2 * xl].sum() + force) / force < 1e-6, (R[2 * xl].sum(), force)         # the left support pulls back with the force ...
assert abs(R[2 * xr].sum() - force) / force < 1e-6, (R[2 * xr].sum(), force)         # ... and the right one carries it
assert abs(res["equilibrium"]["sum_fx"]) < 1e-6 * force and abs(res["equilibrium"]["sum_fy"]) < 1e-6 * force
assert abs(res["energy"] - 0.5 * force * delta) / (0.5 * force * delta) < 1e-6, (res["energy"], 0.5 * force * delta)
assert abs(res["sx"].mean() - E * delta / W) / (E * delta / W) < 1e-6
# the sides are free: the bar gets thinner by nu * strain
assert abs(u[nd[:, 1] > H - 1e-6, 1].mean() - u[nd[:, 1] < 1e-6, 1].mean() + NU * delta / W * H) < 1e-8
# the same bar with the force on it (a pressure) moves exactly as far
pr = -force / (H * TH)                                                          # positive pressure pushes into the material, so a pull is negative
res2 = solve(t, [sup[0], sup[1]], [{"kind": "pressure", "p": pr, "targets": [right]}])
assert abs(res2["u"][xr, 0].mean() - delta) / delta < 1e-6, res2["u"][xr, 0].mean()
assert abs(res2["energy"] - res["energy"]) / res["energy"] < 1e-6
# a free direction really is free; a held one really is held
assert np.ptp(u[xr, 1]) > 0 and np.allclose(u[xl, 0], 0)
# imposed in both directions on the same edge (a shear of the end): reaction in y too
res3 = solve(t, [sup[0], sup[1], {"mode": "disp", "ux": delta, "uy": 0.02, "targets": [right]}], [])
assert np.allclose(res3["u"][xr, 1], 0.02, atol=1e-12) and np.allclose(res3["u"][xr, 0], delta, atol=1e-12)
assert abs(res3["reaction_on_body"][2 * xr + 1].sum()) > 1.0
# a negative displacement pushes
res4 = solve(t, sup[:2] + [{"mode": "disp", "ux": -delta, "uy": None, "targets": [right]}], [])
assert abs(res4["reaction_on_body"][2 * xr].sum() + force) / force < 1e-6

# the nonlinear solver (the bar stays elastic: sigma = 0.05/100*200000 = 100 MPa < yield 250)
t.cb_nl.setChecked(True); t.cb_lin.setChecked(False); t.e_sy.setText("250"); t.e_su.setText("400")
mat = t.read_material()
assert mat["nl_on"]
res5 = pf.solve(t.mesh, mat, [dict(s) for s in sup], [])
assert res5["solver"] == "nonlinear", res5["solver"]
assert np.allclose(res5["u"][xr, 0], delta, atol=1e-9) and np.allclose(res5["u"][xl, 0], 0.0, atol=1e-9)
assert abs(res5["reaction_on_body"][2 * xr].sum() - force) / force < 2e-3, (res5["reaction_on_body"][2 * xr].sum(), force)      # large-displacement terms: well under 0.1 %
# a pull beyond yield: the support force stops growing with the displacement (it is imposed, so the bar yields instead of the load running away)
big = solve(t, sup[:2] + [{"mode": "disp", "ux": 0.5, "uy": None, "targets": [right]}], [])
assert big["solver"] == "nonlinear" and np.allclose(big["u"][xr, 0], 0.5, atol=1e-8)
assert big["reaction_on_body"][2 * xr].sum() < E * 0.5 / W * H * TH * 0.5, "yielding: far less force than the elastic answer"
assert big["reaction_on_body"][2 * xr].sum() > 250 * H * TH * 0.9, "but at least about the yield force"

# no support with a number, nothing loaded: still the old message
t.cb_nl.setChecked(False); t.cb_lin.setChecked(True)
try:
    solve(t, [{"mode": "fixed", "targets": [left]}], [])
    assert False
except pf.ModelError as ex:
    assert "No loads" in str(ex) and "impose a displacement" in str(ex), str(ex)
# only held directions, nothing loaded: no loads either
try:
    solve(t, [{"mode": "disp", "ux": 0.0, "uy": 0.0, "targets": [left]}], [])
    assert False
except pf.ModelError as ex:
    assert "No loads" in str(ex), str(ex)

# ----------------------------------------------------------------------------------------------------------------- the window: button, dialog, table
t, p, ls = new_tab()
t.show(); app.processEvents()
from PyQt6.QtWidgets import QPushButton
sec = [x for x in t.sections if x.title == "Supports"][0]
buttons = [b.text().strip() for b in sec.frame.findChildren(QPushButton)]
assert buttons == ["Fixed", "Displacement...", "Bolt...", "Screw...", "Contact"], buttons
# the dialog: Displacement with nothing selected asks for a selection first
from PyQt6.QtWidgets import QMessageBox
shown = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a[2]))
t.canvas.sel = []
asked = []
orig = sim_disp.ask
sim_disp.ask = lambda parent, title, keys, units, current=None, note=sim_disp.NOTE: (asked.append((title, tuple(keys), dict(units))) or {"ux": None, "uy": 0.25})
t.add_displacement()
assert not t.supports and not asked and len(shown) == 1 and "Select" in shown[0], "nothing selected: no dialog, a sentence"
t.canvas.sel = [("ln", ls[1])]
t.add_displacement()
assert asked == [("Displacement", ("ux", "uy"), {"ux": "mm", "uy": "mm"})], asked
assert t.supports == [{"mode": "disp", "ux": None, "uy": 0.25, "targets": [("ln", ls[1])]}], t.supports
# all blank: refused with a sentence
sim_disp.ask = lambda *a, **k: {"ux": None, "uy": None}
t.canvas.sel = [("ln", ls[3])]
t.add_displacement()
assert len(t.supports) == 1
sim_disp.ask = orig
# the table: type, value, name
t.supports.append({"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]})
t.refresh_lists()
tb = t.cond_table
rows = [[tb.item(r, c).text() for c in range(4)] for r in range(tb.rowCount())]
assert rows[0] == ["Displacement 1", "Displacement (ux, uy) (mm)", "Line %d" % ls[1], "free, 0.25"] or rows[0][:2] == ["Displacement 1", "Displacement (ux, uy) (mm)"], rows
assert rows[0][3] == "free, 0.25" and rows[1][3] == "0, free" and rows[1][0] == "Displacement 2", rows
assert "uy 0.25 mm" in "\n".join(t.cond_list.item(i).text() for i in range(t.cond_list.count())) and "ux held" in t.cond_list.item(1).text()
# editing the value
assert t.set_condition_value(0, "0.5, held") and t.supports[0]["ux"] == 0.5 and t.supports[0]["uy"] == 0.0
assert t.set_condition_value(0, ", 1") and t.supports[0]["ux"] is None and t.supports[0]["uy"] == 1.0
assert not t.set_condition_value(0, "free, free") and t.supports[0]["uy"] == 1.0
assert not t.set_condition_value(0, "7") and not t.set_condition_value(0, "a, b") and t.supports[0]["uy"] == 1.0
# the tag colour of the Outline / view
import sim_tags
assert sim_tags.kind_of("Supports", "Displacement (ux, uy) (mm)") == "support"
# diagnostics name it in words
t.supports = [{"mode": "disp", "ux": 0.0, "uy": 0.25, "targets": [("ln", ls[1])]}]
txt = t.diagnostics_text()
assert "displacement (ux held, uy 0.25 mm" in txt, txt[txt.index("supports:"):][:200]

# ----------------------------------------------------------------------------------------------------------------- an old file
t, p, ls = new_tab()
st = t.export_state()
st["supports"] = [{"mode": "x", "targets": [("ln", ls[3])]}, {"mode": "y", "targets": [("pt", p[0])]}, {"mode": "fixed", "targets": [("ln", ls[1])]}]
t.import_state(st)
assert t.supports[0] == {"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]}, t.supports[0]
assert t.supports[1] == {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", p[0])]}
assert t.supports[2]["mode"] == "fixed"
# the converted old file gives the answer the old supports gave
old = solve(t, [{"mode": "x", "targets": [("ln", ls[3])]}, {"mode": "y", "targets": [("pt", p[0])]}],
            [{"kind": "pressure", "p": -5.0, "targets": [("ln", ls[1])]}])
new = solve(t, t.supports[:2], [{"kind": "pressure", "p": -5.0, "targets": [("ln", ls[1])]}])
assert np.allclose(old["u"], new["u"], atol=1e-12) and abs(old["energy"] - new["energy"]) < 1e-12
assert abs(old["u"][:, 0].max() - 5.0 * H * TH / (E * H * TH) * W) / (5.0 / E * W) < 1e-2          # sigma L / E, the bar of the old file

# ----------------------------------------------------------------------------------------------------------------- units: an imposed displacement is a length
t, p, ls = new_tab()
t.supports = [{"mode": "disp", "ux": 0.1, "uy": None, "targets": [("ln", ls[1])]}, {"mode": "disp", "ux": 0.0, "uy": 2.0, "targets": [("ln", ls[3])]}]
import physics_store as pstore
st = pstore.convert_fea_state(t.export_state(), "Metric (mm, kg, N, s, MPa)", "Metric (m, kg, N, s, Pa)", True)
s0, s1 = st["supports"]
assert abs(s0["ux"] - 1e-4) < 1e-15 and s0["uy"] is None and s1["ux"] == 0.0 and abs(s1["uy"] - 2e-3) < 1e-15, (s0, s1)
back = pstore.convert_fea_state(st, "Metric (m, kg, N, s, Pa)", "Metric (mm, kg, N, s, MPa)", True)
assert abs(back["supports"][0]["ux"] - 0.1) < 1e-12 and abs(back["supports"][1]["uy"] - 2.0) < 1e-12
# a plain relabel keeps the numbers
rel = pstore.convert_fea_state(t.export_state(), "Metric (mm, kg, N, s, MPa)", "Metric (m, kg, N, s, Pa)", False)
assert rel["supports"][0]["ux"] == 0.1

# ----------------------------------------------------------------------------------------------------------------- a study can run it without any load, and can vary the imposed value
t, p, ls = new_tab()
t.supports = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]}, {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", p[0])]},
              {"mode": "disp", "ux": 0.05, "uy": None, "targets": [("ln", ls[1])]}]
t.loads = []
ad = t.study_adapter()
assert ad.ready() is None, ad.ready()
ps = {d["id"]: d for d in ad.params()}
assert "fea.sup2.ux" in ps and "fea.sup0.ux" not in ps and "fea.sup1.uy" not in ps and ps["fea.sup2.ux"]["now"] == "0.05", sorted(ps)
ctx = {}


def run(values):
    spec = ad.prepare(values, ctx)
    assert spec["error"] is None, spec["error"]
    case = spec["run"](lambda *a, **k: None, lambda: False)
    assert case["status"].startswith("ok"), case
    return case


o1 = ad.case_outputs(run({}), ["fea.umax", "fea.vm", "fea.rx"])
o2 = ad.case_outputs(run({"fea.sup2.ux": "0.10"}), ["fea.umax", "fea.vm"])
assert abs(o1["fea.umax"] - np.hypot(0.05, NU * 0.05 / W * H)) < 1e-6 and abs(o2["fea.umax"] / o1["fea.umax"] - 2.0) < 1e-6, (o1, o2)      # |u| of the far corner: the pull and the narrowing
assert abs(o1["fea.vm"] - E * 0.05 / W) < 1e-6 and abs(o1["fea.rx"]) < 1e-6, o1                          # the stress is E * delta / L, the reactions of the two ends cancel
assert abs(o2["fea.vm"] / o1["fea.vm"] - 2.0) < 1e-3
assert t.supports[2]["ux"] == 0.05, "the live tab is untouched"
t.supports = [{"mode": "fixed", "targets": [("ln", ls[3])]}]
assert ad.ready() == "The simulation has no supports or no loads yet."

# the Outline and the workbench count an imposed displacement as what drives the analysis
import sim_outline
t.supports = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]}, {"mode": "disp", "ux": 0.05, "uy": None, "targets": [("ln", ls[1])]}]
mk = sim_outline.generic_marks(t, ["Geometry", "Supports", "Loads", "Results"])
assert mk["Supports"] == "ok" and mk["Loads"] == "ok" and mk["Results"] == "update", mk
t.supports = [{"mode": "disp", "ux": 0.0, "uy": 0.0, "targets": [("ln", ls[3])]}]
mk = sim_outline.generic_marks(t, ["Geometry", "Supports", "Loads", "Results"])
assert mk["Loads"] == "incomplete" and mk["Results"] == "incomplete", "a held direction drives nothing"
t.supports = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]}, {"mode": "disp", "ux": 0.05, "uy": None, "targets": [("ln", ls[1])]}]
sys.path.append(os.path.join(HERE, "dev_addons", "workbench"))
import wb_analysis
assert wb_analysis.ready_fea({"main": {"supports": t.supports, "loads": []}})
assert not wb_analysis.ready_fea({"main": {"supports": [{"mode": "fixed"}], "loads": []}})
assert wb_analysis.ready_fea({"main": {"supports": [{"mode": "fixed"}], "loads": [{"kind": "force"}]}})
assert not wb_analysis.ready_fea({"main": {"supports": [], "loads": [{"kind": "force"}]}})
t.supports = []

# ----------------------------------------------------------------------------------------------------------------- the whole way through the window: mesh, solve, show
t, p, ls = new_tab()
t.supports = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", ls[3])]}, {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", p[0])]},
              {"mode": "disp", "ux": 0.05, "uy": None, "targets": [("ln", ls[1])]}]
t.loads = []
t.run_solve()
assert t.result is not None, t.res_lbl.text() if hasattr(t, "res_lbl") else "no result"
assert abs(np.asarray(t.result["u"])[:, 0].max() - 0.05) < 1e-9
st = t.export_state()
t2, _, _ = new_tab()
t2.import_state(st)
assert t2.supports == t.supports and t2.result is not None
print("ok")
