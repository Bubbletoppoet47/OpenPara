"""The Displacement support of the 3D FEA window: blank = free, 0 = held, a number = moved by exactly that much.
Known answer: a bar 100 x 10 x 10 mm pulled at one end by an imposed displacement delta, held by three planes of symmetry (ux = 0 on the left face, uy = 0 on the face y = 0,
uz = 0 on the face z = 0) has the exact uniform field u = (e x, -nu e y, -nu e z), e = delta / L: stress E e, reaction E e A, energy E e^2 V / 2 - and the force-loaded twin
moves exactly as far.  The reaction of every support is counted by direction (the faces share edges).  Then the window: the button, the dialog, the table, the study."""
import os, sys, tempfile, shutil
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm
import sim_disp

L_, W_, T_ = 100.0, 10.0, 10.0
E_, NU = 200000.0, 0.3
solid = b.Solid.make_box(L_, W_, T_)
g = sg.analyze(solid)


def face_at(axis, side):
    n = np.zeros(3); n[axis] = side
    return next(f["id"] for f in g["faces"] if np.dot(f["normal"], n) > 0.99)


xm, xp, ym, zm = face_at(0, -1), face_at(0, 1), face_at(1, -1), face_at(2, -1)
sig = lambda f: sg.face_sig(g, f)
delta = 0.05
eps = delta / L_
force = E_ * eps * W_ * T_


def setup_with(supports, loads=()):
    s = sm.default_setup()
    s["h"] = 5.0
    s["supports"] = [dict(x) for x in supports]
    s["loads"] = [dict(x) for x in loads]
    return s


SYM = [{"mode": "disp", "faces": [sig(xm)], "ux": 0.0, "uy": None, "uz": None, "name": "Left"},
       {"mode": "disp", "faces": [sig(ym)], "ux": None, "uy": 0.0, "uz": None, "name": "Front"},
       {"mode": "disp", "faces": [sig(zm)], "ux": None, "uy": None, "uz": 0.0, "name": "Bottom"}]
PULL = {"mode": "disp", "faces": [sig(xp)], "ux": delta, "uy": None, "uz": None, "name": "Pull"}

# ----------------------------------------------------------------------------------------------------------------- readiness
s0 = setup_with(SYM + [PULL])
assert sm.check_ready(s0) is None, "a displacement that moves a face is the load"
assert "load" in sm.check_ready(setup_with(SYM)).lower(), "held directions only: nothing drives it"
assert sm.check_ready(setup_with([])) == "Add at least one support."
try:
    sm.resolve(g, setup_with([{"mode": "disp", "faces": [sig(xm)], "ux": None, "uy": None, "uz": None}]))
    assert False
except fem.FemError as ex:
    assert "every direction is blank" in str(ex), str(ex)

# ----------------------------------------------------------------------------------------------------------------- the bar
cache = {}
res = sm.run(g, sm.resolve(g, s0), cache)
nodes, u = np.asarray(res["nodes"]), np.asarray(res["u"])
exact = np.stack([eps * nodes[:, 0], -NU * eps * nodes[:, 1], -NU * eps * nodes[:, 2]], axis=1)
assert np.abs(u - exact).max() < 1e-7, np.abs(u - exact).max()                          # the field is in the element space: exact to the solver
right = np.abs(nodes[:, 0] - L_) < 1e-6
left = np.abs(nodes[:, 0]) < 1e-6
assert np.allclose(u[right, 0], delta, atol=1e-12) and np.allclose(u[left, 0], 0.0, atol=1e-12)
assert abs(res["vm_max"] - E_ * eps) / (E_ * eps) < 1e-5 and abs(np.median(res["vm_el"]) - E_ * eps) / (E_ * eps) < 1e-5, (res["vm_max"], E_ * eps)
assert abs(res["energy"] - 0.5 * force * delta) / (0.5 * force * delta) < 1e-5, (res["energy"], 0.5 * force * delta)
# reactions: counted by direction, so the faces that share edges split them right
reac = dict(res["support_reactions"])
assert abs(reac["Pull"][0] - force) / force < 1e-5 and abs(reac["Left"][0] + force) / force < 1e-5, reac
assert abs(reac["Front"][1]) < 1e-5 * force and abs(reac["Bottom"][2]) < 1e-5 * force, reac          # the symmetry planes carry nothing: the field fits them
assert abs(reac["Pull"][1]) < 1e-5 * force and abs(reac["Pull"][2]) < 1e-5 * force and abs(reac["Left"][1]) < 1e-5 * force
assert np.abs(res["reaction"]).max() < 1e-5 * force, res["reaction"]                      # the whole body: the two ends cancel
assert res["equilibrium"] < 1e-5, res["equilibrium"]
assert res["applied"] == [0.0, 0.0, 0.0]

# the same bar with the force on it moves exactly as far, with the same energy
twin = setup_with(SYM, [{"kind": "force", "faces": [sig(xp)], "f": [force, 0.0, 0.0]}])
res2 = sm.run(g, sm.resolve(g, twin), cache)
assert abs(np.asarray(res2["u"])[right, 0].mean() - delta) / delta < 1e-5
assert abs(res2["energy"] - res["energy"]) / res["energy"] < 1e-5
assert np.abs(np.asarray(res2["u"]) - u).max() < 1e-7

# a negative number pushes; a bigger one scales everything (linear)
neg = setup_with(SYM + [dict(PULL, ux=-2 * delta)])
res3 = sm.run(g, sm.resolve(g, neg), cache)
assert abs(dict(res3["support_reactions"])["Pull"][0] + 2 * force) / force < 1e-5
assert abs(res3["vm_max"] / res["vm_max"] - 2.0) < 1e-5

# imposed in two directions at once: the end is also moved sideways (a shear of the end)
two = setup_with(SYM + [dict(PULL, uy=0.02)])
res4 = sm.run(g, sm.resolve(g, two), cache)
u4 = np.asarray(res4["u"])
assert np.allclose(u4[right, 1], 0.02, atol=1e-12) and np.allclose(u4[right, 0], delta, atol=1e-12)
assert abs(dict(res4["support_reactions"])["Pull"][1]) > 1.0, "moving it sideways takes a force"

# a face with one direction imposed and one held (the end cannot move in z)
tri = setup_with(SYM[:1] + [{"mode": "disp", "faces": [sig(ym)], "ux": None, "uy": 0.0, "uz": None, "name": "Front"}, SYM[2], dict(PULL, uy=None, uz=0.0)])
res5 = sm.run(g, sm.resolve(g, tri), cache)
assert np.allclose(np.asarray(res5["u"])[right, 2], 0.0, atol=1e-12) and np.allclose(np.asarray(res5["u"])[right, 0], delta, atol=1e-12)

# the old supports keep working beside it: Fixed on the left, the pull on the right
mix = setup_with([{"mode": "fixed", "faces": [sig(xm)], "name": "Wall"}, dict(PULL)])
res6 = sm.run(g, sm.resolve(g, mix), cache)
u6 = np.asarray(res6["u"])
assert np.allclose(u6[right, 0], delta, atol=1e-12) and np.allclose(u6[left], 0.0, atol=1e-12)
assert res6["equilibrium"] < 1e-5, res6["equilibrium"]
assert dict(res6["support_reactions"])["Pull"][0] > 0.9 * force, "the clamped end resists the Poisson contraction: a little more than E e A"

# a displacement imposed where a one-direction (slanted) hold also acts is refused in words, not solved wrongly
q = sm.get_mesh(g, 5.0, cache, lambda: False, lambda t: None, None)
ndl = np.where(np.abs(np.asarray(q["nodes"])[:, 0]) < 1e-6)[0]
ndr = np.where(np.abs(np.asarray(q["nodes"])[:, 0] - L_) < 1e-6)[0]
try:
    fem.solve(q, E_, NU, [(ndl, np.array([1.0, 1.0, 0.0])), (ndl, {"disp": (0.5, None, None)}), (ndr, None)], np.zeros(3 * len(q["nodes"])))
    assert False
except fem.FemError as ex:
    assert "imposed on nodes that also belong to a bearing or a one-direction support" in str(ex), str(ex)
# ... but holding the same nodes at 0 is fine (the frame of the node takes it)
u_, reac_, info_, K_, D_ = fem.solve(q, E_, NU, [(ndl, np.array([1.0, 1.0, 0.0])), (ndl, {"disp": (0.0, None, None)}), (ndr, None)],
                                     np.zeros(3 * len(q["nodes"])) + 1e-3)
assert np.isfinite(u_).all()
# nothing held at all
try:
    fem.solve(q, E_, NU, [(ndl, {"disp": (None, None, None)}), (ndr, None)], np.zeros(3 * len(q["nodes"])))
    assert False
except fem.FemError as ex:
    assert "holds nothing" in str(ex), str(ex)

# ----------------------------------------------------------------------------------------------------------------- the window
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pm, sk_tools as sk
import solid_tab, solid_study
import sim_project as sp

T = tempfile.mkdtemp(prefix="opara_solid_")
d = pm.Document(); d.params = {"T": "10"}
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
r = sk.add_rect_corner(m, (0, 0), (100, 10))
m.add_con("dim_h", [("ln", r["lns"][0])], value=100.0); m.add_con("dim_v", [("ln", r["lns"][1])], value=10.0)
sk.solve_model(m); d.store_sketch(s["id"])
d.add(pm.new_feature("extrude", sketch=s["id"], depth="T")); d.rebuild()
part = os.path.join(T, "bar.gpd"); open(part, "w").write(d.to_json())
w = solid_tab.SolidWindow(threaded=False)
assert w.create_project(os.path.join(T, "bar_study")) and w.import_file(part), MSGS
shutil.move(part, part + ".away")


def face(n):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], n) > 0.99)


left_, right_, front_, bottom_ = face([-1, 0, 0]), face([1, 0, 0]), face([0, -1, 0]), face([0, 0, -1])
sec = [x for x in w.sections if x.title == "Supports"][0]
texts = [bt.text().strip() for bt in sec.frame.findChildren(QPushButton)]
assert texts == ["Fixed", "Displacement...", "One direction (normal)", "Bearing (hole face)"], texts
# the dialog is asked for the numbers (shown in the units of the program, kept in mm)
asked = []
orig_ask = sim_disp.ask
sim_disp.ask = lambda parent, title, keys, units, current=None, note=sim_disp.NOTE: (asked.append((title, tuple(keys), dict(units), dict(current or {}))) or {"ux": 0.0, "uy": None, "uz": None})
w.select_faces([])
assert not w.add_support("disp") and not asked and "Select the face" in w.status_lbl.text(), w.status_lbl.text()
w.select_faces([left_])
assert w.add_support("disp")
assert asked[0][0] == "Displacement" and asked[0][1] == ("ux", "uy", "uz") and asked[0][2]["ux"] == "mm", asked
sp0 = w.setup["supports"][0]
assert sp0["mode"] == "disp" and sp0["ux"] == 0.0 and sp0["uy"] is None and sp0["uz"] is None and sp0["name"] == "Displacement support 1", sp0
# nothing is held: refused with a sentence, nothing added
sim_disp.ask = lambda *a, **k: {"ux": None, "uy": None, "uz": None}
w.select_faces([front_])
assert not w.add_support("disp") and len(w.setup["supports"]) == 1
# values given by a script (mm): imposed on the right face
sim_disp.ask = orig_ask
w.select_faces([right_])
assert w.add_support("disp", values={"ux": 0.05})
w.select_faces([front_]); assert w.add_support("disp", values={"uy": 0.0})
w.select_faces([bottom_]); assert w.add_support("disp", values={"uz": 0})
assert not w.add_support("disp", values={})
assert [x["mode"] for x in w.setup["supports"]] == ["disp"] * 4 and w.setup["supports"][1]["ux"] == 0.05 and w.setup["supports"][1]["uy"] is None
assert w.ready() is None, w.ready()
# the table and the list
tb = w.cond_table
rows = [[tb.item(i, c).text() for c in range(4)] for i in range(tb.rowCount())]
assert rows[0] == ["Displacement support 1", "Displacement (ux, uy, uz) (mm)", "1 face", "0, free, free"], rows[0]
assert rows[1][3] == "0.05, free, free" and rows[2][3] == "free, 0, free" and rows[3][3] == "free, free, 0", rows
assert "displacement (ux held, uy free, uz free)" in w.sup_list.item(0).text() and "ux 0.05 mm" in w.sup_list.item(1).text(), w.sup_list.item(1).text()
# editing: the dialog opens with the numbers of the row
sim_disp.ask = lambda parent, title, keys, units, current=None, note=sim_disp.NOTE: (asked.append(("edit", dict(current))) or {"ux": 0.1, "uy": None, "uz": None})
assert w.edit_displacement(1)
assert asked[-1] == ("edit", {"ux": 0.05, "uy": None, "uz": None}) and w.setup["supports"][1]["ux"] == 0.1
w.cond_table.setCurrentCell(1, 0)
assert w.edit_condition() and w.setup["supports"][1]["ux"] == 0.1
w.setup["supports"][1]["ux"] = 0.05
sim_disp.ask = orig_ask
# solve through the window, no load at all
w.set_size("5"); w.inputs_changed()
assert w.run_mesh() and w.run_solve() and w.result is not None, MSGS[-1:] + [w.status_lbl.text()]
res_w = w.result
assert abs(res_w["vm_max"] - E_ * eps) / (E_ * eps) < 1e-4, res_w["vm_max"]
assert abs(dict(res_w["support_reactions"])["Displacement support 2"][0] - force) / force < 1e-4, res_w["support_reactions"]
# save and reopen: the numbers come back (blank stays blank, 0 stays 0)
assert w.save() and os.path.isfile(sp.state_path(w.path))
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
back = [(x["mode"], x["ux"], x["uy"], x["uz"]) for x in w2.setup["supports"]]
assert back == [("disp", 0.0, None, None), ("disp", 0.05, None, None), ("disp", None, 0.0, None), ("disp", None, None, 0.0)], back
assert w2.ready() is None
rows2 = [[w2.cond_table.item(i, c).text() for c in range(4)] for i in range(w2.cond_table.rowCount())]
assert rows2 == rows and rows2[1][3] == "0.05, free, free", rows2
# the study can vary the imposed number, with no load
ad = solid_study.SolidStudy(w) if hasattr(solid_study, "SolidStudy") else None
if ad is None:
    cls = [c for n, c in vars(solid_study).items() if isinstance(c, type) and hasattr(c, "params") and hasattr(c, "prepare")][0]
    ad = cls(w)
ps = {p_["id"]: p_ for p_ in ad.params()}
assert "sf.sup1.ux" in ps and "sf.sup0.ux" not in ps and "sf.sup2.uy" not in ps and ps["sf.sup1.ux"]["now"] == "0.05", sorted(k for k in ps if "sup" in k)
ctx = {}
spec = ad.prepare({"sf.sup1.ux": "0.1"}, ctx)
assert spec["error"] is None, spec["error"]
case = spec["run"](lambda *a, **k: None, lambda: False)
assert case["status"].startswith("ok"), case
o = ad.case_outputs(case, ["sf.vm", "sf.rx"])
assert abs(o["sf.vm"] - 2 * E_ * eps) / (2 * E_ * eps) < 1e-4, o
assert w.setup["supports"][1]["ux"] == 0.05, "the window itself is untouched"
print("ok")
