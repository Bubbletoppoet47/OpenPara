"""3D FEA: the bearing support - for the round (cylindrical) face of a hole; it holds the face against moving sideways (in and out along the radius) and along
the axis, and leaves the turn about the axis free.

Model (no window): the faces of a part with holes know their axis and radius; a bearing on two holes solves, the nodes of the hole faces do not move along the
radius or the axis (to the penalty's accuracy) but do slide along the face, the loads and the reactions are in equilibrium, the part is a little softer than with the same
faces Fixed; one bearing alone is refused with a plain sentence about the turn; a flat face is refused; with an axisymmetric load a bearing (plus one pin that
stops the turn) gives the same answer as Fixed on the face, and that pin carries nothing.
Window: the button, a bearing on a flat face is refused with a reason, the table, the solve, the reaction, save and reopen; a bonded assembly with a hole through
both parts.   python test_solid_bearing.py"""
import faulthandler
faulthandler.dump_traceback_later(290, exit=True)
import os, sys, tempfile, shutil, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UDIR = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UDIR
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import solid_geom as sg, solid_fem as fem, solid_model as sm, solid_asm as sa
import solid_tab
import sim_project as sp
import pm_model as pm, sk_tools as sk, asm_model as am

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


STEEL = {"name": "Steel", "density": 7850.0, "E_MPa": 200000.0, "nu": 0.3, "Sy_MPa": 250.0, "Su_MPa": 400.0}

# ------------------------------------------------------------------------------------------------ the faces know their axis
plate = b.Box(80, 40, 12) - b.Pos(-25, 0, 0) * b.Cylinder(6, 12) - b.Pos(25, 0, 0) * b.Cylinder(6, 12)
g = sg.analyze(plate)
cyls = [f for f in g["faces"] if f["kind"] == "cylinder"]
ok(len(cyls) == 2 and all(f.get("cyl") for f in cyls), "the two hole faces carry their axis and radius")
c0 = sorted(cyls, key=lambda f: f["center"][0])[0]["cyl"]
ok(abs(c0["radius"] - 6.0) < 1e-6 and abs(abs(c0["axis"][2]) - 1.0) < 1e-9 and abs(c0["origin"][0] + 25.0) < 1e-6 and abs(c0["origin"][1]) < 1e-6,
   f"hole 1: radius {c0['radius']}, axis {np.round(c0['axis'], 6).tolist()}, through {np.round(c0['origin'], 6).tolist()}")
ok(all("cyl" not in f for f in g["faces"] if f["kind"] != "cylinder"), "flat faces have none")
hole_ids = [f["id"] for f in sorted(cyls, key=lambda f: f["center"][0])]
top = next(f["id"] for f in g["faces"] if f["kind"] == "plane" and f["normal"][1] > 0.99)
left = next(f["id"] for f in g["faces"] if f["kind"] == "plane" and f["normal"][0] < -0.99)
ok(set(sm.MODES) == {"fixed", "slide", "bearing"}, f"the support kinds: {sorted(sm.MODES)}")


def setup(supports, load=(0.0, -2000.0, 0.0), face=None, h=4.0):
    s = sm.default_setup()
    s["h"] = h
    s["supports"] = supports
    s["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, top if face is None else face)], "f": list(load)}]
    return s


def sup(mode, fids):
    return {"mode": mode, "faces": [sg.face_sig(g, f) for f in fids]}


# ------------------------------------------------------------------------------------------------ two bearings
r_b = sm.run(g, sm.resolve(g, setup([sup("bearing", hole_ids)])), {})
R = r_b["reaction"]
ok(abs(R[1] - 2000.0) < 1e-3 * 2000.0 and abs(R[0]) < 2.0 and abs(R[2]) < 2.0, f"the reaction answers the load: {np.round(R, 3).tolist()} against 2000 N")
ok(r_b["equilibrium"] < 1e-6, f"equilibrium {r_b['equilibrium']:.1e}")
nodes, u = r_b["nodes"], r_b["u"]
umax = float(np.linalg.norm(u, axis=1).max())
q = sm.get_mesh(g, 4.0, {}, lambda: False, lambda t: None, sm.resolve(g, setup([sup("bearing", hole_ids)]))["mesh"])
worst_rad = worst_ax = max_tan = 0.0
for fid in hole_ids:
    cy = g["faces"][fid]["cyl"]
    nd = np.unique(q["ftri"][fid])
    a, rad = fem.bearing_dirs(q["nodes"], nd, (cy["origin"], cy["axis"]))
    uu = u[nd]
    worst_rad = max(worst_rad, float(np.abs((uu * rad).sum(axis=1)).max()))
    worst_ax = max(worst_ax, float(np.abs(uu @ a).max()))
    tan = uu - (uu * rad).sum(axis=1)[:, None] * rad - (uu @ a)[:, None] * a
    max_tan = max(max_tan, float(np.linalg.norm(tan, axis=1).max()))
ok(worst_rad < 1e-6 * umax and worst_ax < 1e-6 * umax, f"the hole faces do not move along the radius ({worst_rad:.1e}) or the axis ({worst_ax:.1e}); umax {umax:.4g} mm")
ok(max_tan > 0.05 * umax, f"but they slide along the face: {max_tan:.4g} mm against umax {umax:.4g} mm")
ok(len(r_b["support_reactions"]) == 1 and abs(np.asarray(r_b["support_reactions"][0][1])[1] - 2000.0) < 3.0, f"the support's own reaction: {r_b['support_reactions']}")

r_f = sm.run(g, sm.resolve(g, setup([sup("fixed", hole_ids)])), {})
um_f = float(np.linalg.norm(r_f["u"], axis=1).max())
ok(um_f <= umax * (1.0 + 1e-6) and umax < 5.0 * um_f, f"Fixed on the same faces is as stiff or stiffer: {um_f:.4g} mm against {umax:.4g} mm with the bearings")

# ------------------------------------------------------------------------------------------------ what is refused
for why, sups, words in (("one bearing alone", [sup("bearing", [hole_ids[0]])], ("turn", "second")),
                         ("a bearing on a flat face", [sup("bearing", [left]), sup("fixed", [hole_ids[1]])], ("round", "cylindrical", "plane"))):
    try:
        sm.run(g, sm.resolve(g, setup(sups)), {})
        ok(False, f"{why} must be refused")
    except fem.FemError as ex:
        ok(all(w in str(ex) for w in words), f"{why} is refused in plain words: {ex}")
r_one = None
try:
    r_one = sm.run(g, sm.resolve(g, setup([sup("bearing", [hole_ids[0]]), sup("slide", [next(f["id"] for f in g["faces"] if f["kind"] == "plane" and f["normal"][1] < -0.99)])])), {})
except fem.FemError as ex:
    print("one bearing and one slide:", ex)
ok(r_one is not None, "one bearing and a one-direction support on the bottom face is enough (the slide holds y at a distance from the hole, which stops the turn)")

# ------------------------------------------------------------------------------------------------ the same answer as Fixed where the turn does not matter
tube = b.Pos(0, 0, 0) * (b.Cylinder(30, 20) - b.Cylinder(10, 20))
gt = sg.analyze(tube)
inner = next(f["id"] for f in gt["faces"] if f["kind"] == "cylinder" and f["cyl"]["radius"] < 15)
outer = next(f["id"] for f in gt["faces"] if f["kind"] == "cylinder" and f["cyl"]["radius"] > 15)
st = sm.default_setup(); st["h"] = 5.0
st["supports"] = [{"mode": "bearing", "faces": [sg.face_sig(gt, inner)]}]
st["loads"] = [{"kind": "pressure", "faces": [sg.face_sig(gt, outer)], "p": 10.0}]
rt = sm.resolve(gt, st)
qt = sm.get_mesh(gt, 5.0, {}, lambda: False, lambda t: None, rt["mesh"])
nn = len(qt["nodes"])
t6 = qt["ftri"][outer]
nv, area = fem.outward_normals(qt, qt["faces"][outer])
fe = (-10.0 * nv) * (area / 3.0)[:, None]
force = np.zeros(3 * nn)
for j in (3, 4, 5):
    for c in range(3):
        np.add.at(force, 3 * t6[:, j] + c, fe[:, c])
nd_in = np.unique(qt["ftri"][inner])
cy = gt["faces"][inner]["cyl"]
a_, rad_ = fem.bearing_dirs(qt["nodes"], nd_in, (cy["origin"], cy["axis"]))
pin = int(nd_in[np.argmax(qt["nodes"][nd_in][:, 0])])                 # the node at the +x side of the hole: the turn about z moves it along y
tang = np.cross(a_, rad_[list(nd_in).index(pin)])
uB, reB, infoB, _K, _D = fem.solve(qt, 200000.0, 0.3, [(nd_in, {"bearing": (cy["origin"], cy["axis"])}), (np.array([pin]), tang)], force)
uF, reF, infoF, _K, _D = fem.solve(qt, 200000.0, 0.3, [(nd_in, None)], force)
dB, dF = np.linalg.norm(uB, axis=1).max(), np.linalg.norm(uF, axis=1).max()
ok(abs(dB - dF) / dF < 0.02, f"a tube under outside pressure: umax {dB:.6g} with a bearing (and the pin) against {dF:.6g} Fixed")
carried = float(np.abs(10.0 * 2 * np.pi * 30.0 * 20.0))
ok(float(np.linalg.norm(reB[1])) < 0.01 * carried, f"the pin that stops the turn carries {np.linalg.norm(reB[1]):.3g} N of the {carried:.3g} N the pressure puts on the tube")

# ------------------------------------------------------------------------------------------------ a one-direction support on a slanted face (it shares the solver)
bar = b.Solid.make_box(60, 20, 20) - b.Pos(60, 10, 10) * b.Rot(0, 0, 30) * b.Pos(20, 0, 0) * b.Box(40, 80, 40)
go = sg.analyze(bar)
obl = next(f for f in go["faces"] if f["kind"] == "plane" and 0.3 < abs(f["normal"][0]) < 0.95)
so = sm.default_setup(); so["h"] = 5.0
so["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(go, next(f["id"] for f in go["faces"] if f["normal"][0] < -0.99))]},
                  {"mode": "slide", "faces": [sg.face_sig(go, obl["id"])]}]
so["loads"] = [{"kind": "force", "faces": [sg.face_sig(go, next(f["id"] for f in go["faces"] if f["normal"][2] > 0.99))], "f": [0.0, 0.0, -500.0]}]
ro = sm.resolve(go, so)
res_o = sm.run(go, ro, {})
qo = sm.get_mesh(go, 5.0, {}, lambda: False, lambda t: None, ro["mesh"])
nd_o = np.unique(qo["ftri"][obl["id"]])
n_o = sm.face_normal(qo, go, obl["id"])
ok(res_o["equilibrium"] < 1e-9, f"slanted one-direction support: equilibrium {res_o['equilibrium']:.1e} (the old penalty failed its residual check here)")
ok(float(np.abs(res_o["u"][nd_o] @ n_o).max()) < 1e-9 * max(res_o["umax"], 1e-12), "the slanted face does not move along its normal")
rs = np.asarray(res_o["support_reactions"][1][1])
ok(np.linalg.norm(rs) > 1.0 and abs(abs(rs @ n_o) - np.linalg.norm(rs)) < 1e-6 * np.linalg.norm(rs), f"and it carries a reaction along that normal: {np.round(rs, 3).tolist()}")

# ------------------------------------------------------------------------------------------------ the window
T = tempfile.mkdtemp(prefix="opara_bear_")
w = solid_tab.SolidWindow(threaded=False)


def make_plate(path):
    """A plate 80 x 40 x 12 with two holes of radius 6 (axis along z) as an OpenPara part."""
    d = pm.Document()
    d.params = {"H": "12"}
    s_ = d.add(pm.new_feature("sketch", plane={"base": "Top"}))
    d.rebuild()
    m = d.models[s_["id"]]
    sk.add_rect_corner(m, (0, 0), (80, 40))
    sk.add_circle(m, (20, 20), (26, 20))
    sk.add_circle(m, (60, 20), (66, 20))
    sk.solve_model(m)
    d.store_sketch(s_["id"])
    d.add(pm.new_feature("extrude", sketch=s_["id"], depth="H"))
    d.rebuild()
    assert d.solid is not None
    with open(path, "w", encoding="utf-8") as f:
        f.write(d.to_json())


part = os.path.join(T, "plate.gpd")
make_plate(part)
ok(w.create_project(os.path.join(T, "study")) and w.import_file(part) and w.geom is not None, f"a plate with two holes opens {MSGS[-1:]}")
texts = [b_.text().strip() for b_ in w.findChildren(QPushButton)]
ok(any(t.startswith("Bearing") for t in texts) and "Bolt / pin hole" not in texts, f"the Bearing button is there, the old bolt button is not ({[t for t in texts if 'earing' in t or 'olt' in t]})")
gw = w.geom
hw = sorted([f["id"] for f in gw["faces"] if f["kind"] == "cylinder"], key=lambda i: gw["faces"][i]["center"][0])
tw = next(f["id"] for f in gw["faces"] if f["kind"] == "plane" and f["normal"][1] > 0.99)       # the side at y = 40
lw = next(f["id"] for f in gw["faces"] if f["kind"] == "plane" and f["normal"][0] < -0.99)
w.select_faces([lw])
ok(not w.add_support("bearing") and "round" in w.status_lbl.text() and "plane" in w.status_lbl.text() and not w.setup["supports"],
   f"a bearing on a flat face is refused with a reason: {w.status_lbl.text()[:130]}")
w.select_faces(hw)
ok(w.add_support("bearing") and w.setup["supports"][0]["mode"] == "bearing" and len(w.setup["supports"][0]["faces"]) == 2, "both hole faces take one bearing")
ok(w.setup["supports"][0].get("name") == "Bearing support 1", f"it is called {w.setup['supports'][0].get('name')}")
w.select_faces([tw]); ok(w.add_load("force", {"f": [0.0, -2000.0, 0.0]}), "a force on the top face")
w.set_size("4"); w.inputs_changed()
ok(w.ready() is None, f"ready: {w.ready()}")
ok(w.run_solve() and w.result is not None, f"it solves: {w.status_lbl.text()[:100]}")
ok(abs(w.result["reaction"][1] - 2000.0) < 2.0 and w.result["equilibrium"] < 1e-6, f"reaction {np.round(w.result['reaction'], 3).tolist()}, equilibrium {w.result['equilibrium']:.1e}")
ok("Bearing" in w.sup_list.item(0).text() or "bearing" in w.sup_list.item(0).text(), f"the list says so: {w.sup_list.item(0).text()}")
w.save()
w2 = solid_tab.SolidWindow.open_project(None, w.path, threaded=False)
ok(w2.setup["supports"][0]["mode"] == "bearing" and w2.ready() is None, "save and reopen keep the bearing")
ok(w2.run_solve() and abs(w2.result["umax"] - w.result["umax"]) / w.result["umax"] < 1e-6, "and the reopened project gives the same answer")
# one bearing alone: the window says why
w2.setup["supports"][0]["faces"] = w2.setup["supports"][0]["faces"][:1]
w2.inputs_changed()
w2.say("")
w2.run_solve()
ok("turn about that axis" in w2.status_lbl.text() and "second bearing" in w2.status_lbl.text(), f"one bearing alone: the window says why ({w2.status_lbl.text()[:150]})")

# ------------------------------------------------------------------------------------------------ a bonded assembly with a hole through both parts
ga = sa.analyze_assembly([("lower", b.Pos(0, 0, 5.0) * b.Box(60, 30, 10) - b.Pos(-20, 0, 5.0) * b.Cylinder(5, 10) - b.Pos(20, 0, 5.0) * b.Cylinder(5, 10), STEEL),
                          ("upper", b.Pos(0, 0, 15.0) * b.Box(60, 30, 10) - b.Pos(-20, 0, 15.0) * b.Cylinder(5, 10) - b.Pos(20, 0, 15.0) * b.Cylinder(5, 10), STEEL)])
holes_a = [f["id"] for f in ga["faces"] if f["kind"] == "cylinder"]
ok(len(holes_a) == 4 and all(ga["faces"][i].get("cyl") for i in holes_a), f"an assembly: four hole faces (two per part), each with its axis ({len(holes_a)})")
topa = next(f["id"] for f in ga["faces"] if f["kind"] == "plane" and f["normal"][2] > 0.99 and not f.get("interface"))
sa_ = sm.default_setup(); sa_["h"] = 6.0
sa_["supports"] = [{"mode": "bearing", "faces": [sg.face_sig(ga, i) for i in holes_a]}]
sa_["loads"] = [{"kind": "force", "faces": [sg.face_sig(ga, topa)], "f": [0.0, 0.0, -3000.0]}]
ra = sm.run(ga, sm.resolve(ga, sa_), {})
ok(abs(ra["reaction"][2] - 3000.0) < 3.0 and ra["equilibrium"] < 1e-6 and len(ra["bodies"]) == 2, f"the stack: reaction {np.round(ra['reaction'], 3).tolist()} for 3000 N, equilibrium {ra['equilibrium']:.1e}")

shutil.rmtree(T, ignore_errors=True)
print("FAILED:" if FAILS else "OK bearing", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
