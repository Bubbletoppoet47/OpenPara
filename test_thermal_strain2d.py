"""Thermal strain in the 2D structural solver (physics_fea.solve(..., thermal={"T": nodal temperatures})), against closed-form answers.

  * a bar heated by dT with nothing holding it grows freely by alpha dT in every direction and carries NO stress (plane stress), (1 + nu) alpha dT in the plane
    and sigma_z = -E alpha dT in plane strain
  * a bar held between two walls (ux = 0 at both ends) carries sigma_x = -E alpha dT (plane stress) or -E alpha dT / (1 - nu) (plane strain), the wall reaction
    is that stress times the section, and the elastic strain energy is half sigma^2 / E times the volume
  * a temperature that rises linearly across the bar (T = Tref + g y) bends it without stress: the quadratic element gives the exact displacement
    u_x = alpha g x y, u_y = alpha g (y^2 - x^2) / 2
  * two materials in series (nu = 0) held between two walls: sigma = -dT (alpha1 L1 + alpha2 L2) / (L1/E1 + L2/E2)
  * a thermal load needs no other load, adds to a mechanical one (superposition), asks for alpha, and the nonlinear solver says it does not include it"""
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
import physics_tab, sim_tab
import physics_fea as pf

W, H = 100.0, 20.0
E, NU, TH = 200000.0, 0.26, 1.0
ALPHA, DT, TREF = 12e-6, 100.0, 293.15
SIG = E * ALPHA * DT                                                  # 240 MPa


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


t, p, ls = new_tab()
NODES = np.asarray(t.mesh["nodes"], float)
left, right = ("ln", ls[3]), ("ln", ls[1])
PIN = [{"mode": "disp", "ux": 0.0, "uy": 0.0, "targets": [("pt", p[0])]}, {"mode": "disp", "ux": 0.0, "uy": None, "targets": [("pt", p[3])]}]       # a free bar: just no rigid-body motion
WALLS = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [left]}, {"mode": "disp", "ux": 0.0, "uy": None, "targets": [right]},
         {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", p[0])]}]                                                                    # held between two walls


def material(order=2, mode="stress", alpha=ALPHA, **kw):
    mat = dict(t.read_material())
    mat.update({"E": E, "nu": NU, "t": TH, "order": order, "mode": mode, "lin_on": True, "nl_on": False, "Tref": TREF})
    if alpha is not None:
        mat["alpha"] = alpha
    else:
        mat.pop("alpha", None)                        # the tab's material box already holds the library value of its material: "no coefficient" means taking it out
    mat.update(kw)
    return mat


def run(sup, loads=(), thermal=None, **kw):
    return pf.solve(t.mesh, material(**kw), [dict(s) for s in sup], [dict(l) for l in loads], thermal=thermal)


def heated(dT=DT):
    return {"T": np.full(len(NODES), TREF + dT)}


def nodes_of(res):
    return np.asarray(res["mesh"]["nodes"]) if res["mesh"] else NODES


def at(res, x, y):
    nd = nodes_of(res)
    k = int(np.argmin(np.hypot(nd[:, 0] - x, nd[:, 1] - y)))
    assert np.hypot(nd[k, 0] - x, nd[k, 1] - y) < 1e-6, (x, y)
    return k


# ------------------------------------------------------------------------------------------------------- 1. a free bar grows and carries no stress
for order in (1, 2):
    r = run(PIN, thermal=heated(), order=order)
    k = at(r, W, H)
    assert abs(r["u"][k, 0] - ALPHA * DT * W) < 1e-9 and abs(r["u"][k, 1] - ALPHA * DT * H) < 1e-9, (order, r["u"][k])
    s = max(np.abs(r[q]).max() for q in ("sx", "sy", "txy", "szz"))
    assert s < 1e-9 * SIG, (order, s)
    assert r["energy"] < 1e-9, r["energy"]                                    # no elastic energy: the strain is all thermal
    assert r["thermal"]["T_max"] == TREF + DT and r["solver"] == "linear"
    assert any("THERMAL STRAIN" in n for n in r["notes"])
    print("ok   a free bar grows by alpha dT and carries no stress (element order %d)" % order)

# a cooling bar shrinks by the same amount the other way
r = run(PIN, thermal=heated(-DT))
k = at(r, W, H)
assert abs(r["u"][k, 0] + ALPHA * DT * W) < 1e-9
print("ok   a cooled bar shrinks")

# a temperature equal to the reference temperature: nothing happens
r = run(PIN, thermal=heated(0.0))
assert np.abs(r["u"]).max() < 1e-12 and np.abs(r["sx"]).max() < 1e-9
print("ok   at the reference temperature there is no strain")

# plane strain: the thickness is held, so the plane grows by (1 + nu) alpha dT and sigma_z = -E alpha dT
r = run(PIN, thermal=heated(), mode="strain")
k = at(r, W, H)
assert abs(r["u"][k, 0] - (1 + NU) * ALPHA * DT * W) < 1e-9, r["u"][k]
assert np.abs(r["sx"]).max() < 1e-9 * SIG and np.abs(r["sy"]).max() < 1e-9 * SIG
assert np.allclose(r["szz"], -SIG, rtol=1e-9), (r["szz"].min(), r["szz"].max())
print("ok   plane strain: growth (1 + nu) alpha dT and sigma_z = -E alpha dT")

# ------------------------------------------------------------------------------------------------------- 2. held between two walls
for order in (1, 2):
    r = run(WALLS, thermal=heated(), order=order)
    assert np.allclose(r["sx"], -SIG, rtol=1e-9) and np.abs(r["sy"]).max() < 1e-7 * SIG, (order, r["sx"].min(), r["sx"].max())
    nd = nodes_of(r)
    Rx = r["reaction_on_body"][0::2]
    left_R = float(Rx[np.abs(nd[:, 0]) < 1e-6].sum())
    assert abs(left_R - SIG * H * TH) < 1e-6 * SIG * H, (order, left_R, SIG * H * TH)             # the wall pushes back with sigma times the section
    V = W * H * TH
    assert abs(r["energy"] - 0.5 * SIG ** 2 / E * V) < 1e-9 * 0.5 * SIG ** 2 / E * V, (order, r["energy"])
    assert abs(r["equilibrium"]["sum_fx"]) < 1e-6 * SIG * H
    print("ok   a bar held between walls carries -E alpha dT, reacts with it and stores half sigma^2/E per volume (order %d)" % order)

r = run(WALLS, thermal=heated(), mode="strain")
s_pe = -SIG / (1 - NU)
assert np.allclose(r["sx"], s_pe, rtol=1e-9) and np.allclose(r["szz"], s_pe, rtol=1e-9), (r["sx"].min(), r["szz"].min(), s_pe)
print("ok   plane strain, held between walls: sigma_x = sigma_z = -E alpha dT / (1 - nu)")

# ------------------------------------------------------------------------------------------------------- 3. a temperature that rises across the bar bends it without stress
g = 5.0                                                                   # kelvin per mm: 100 K from the bottom to the top
r = run(PIN, thermal={"T": TREF + g * NODES[:, 1]}, order=2)
nd = nodes_of(r)
ux = ALPHA * g * nd[:, 0] * nd[:, 1]
uy = 0.5 * ALPHA * g * (nd[:, 1] ** 2 - nd[:, 0] ** 2)
err = max(np.abs(r["u"][:len(nd), 0] - ux).max(), np.abs(r["u"][:len(nd), 1] - uy).max())
assert err < 1e-10, err
assert max(np.abs(r[q]).max() for q in ("sx", "sy", "txy")) < 1e-8 * SIG
print("ok   a linear temperature gradient bends the bar: the quadratic element is exact (u_x = alpha g x y, u_y = alpha g (y^2 - x^2) / 2)")
r1 = run(PIN, thermal={"T": TREF + g * NODES[:, 1]}, order=1)
k = at(r1, W, H)
assert abs(r1["u"][k, 0] - ALPHA * g * W * H) < 0.05 * ALPHA * g * W * H                 # the 3-node triangle is close, not exact
print("ok   the 3-node triangle is close (within 5 %)")

# ------------------------------------------------------------------------------------------------------- 4. two materials in series
def two_part_tab():
    """The bar as two rectangles that share the edge x = W/2: the mesh has element edges along the joint and every triangle belongs to one of the two regions."""
    host = sim_tab.SimHost.__new__(sim_tab.SimHost)
    host.doc = None; host.m = sim_tab._HostModel(); host._restoring = False; host.status = lambda t_: None; host.sim = None
    host.sketch_list = lambda: []
    t2 = physics_tab.PhysicsTab(host)
    m = sc.Model()
    pts = [m.add_point(*c) for c in ((0, 0), (W / 2, 0), (W, 0), (W, H), (W / 2, H), (0, H))]
    lns = [m.add_line(pts[i_], pts[(i_ + 1) % 6]) for i_ in range(6)] + [m.add_line(pts[1], pts[4])]
    t2.set_model(m, "two")
    t2.run_task = lambda title, fn: ("ok", fn(lambda *a, **k: None, lambda: False))
    t2.e_h.setText("5")
    t2.run_mesh()
    return t2, pts, lns


t2, pts2, lns2 = two_part_tab()
assert t2.mesh.get("tri_face") is not None
nd2 = np.asarray(t2.mesh["nodes"], float)
cx2 = nd2[t2.mesh["tris"]][:, :, 0].mean(axis=1)
tf = np.asarray(t2.mesh["tri_face"])
face_left = {int(f) for f in np.unique(tf[cx2 < W / 2])}
face_right = {int(f) for f in np.unique(tf[cx2 > W / 2])}
assert len(face_left) == 1 and len(face_right) == 1 and not (face_left & face_right), (face_left, face_right)          # the regions are the two halves
fl, fr = face_left.pop(), face_right.pop()
walls2 = [{"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", lns2[5])]}, {"mode": "disp", "ux": 0.0, "uy": None, "targets": [("ln", lns2[2])]},
          {"mode": "disp", "ux": None, "uy": 0.0, "targets": [("pt", pts2[0])]}]
E1, E2 = 100000.0, 300000.0


def series(a1, a2):
    rm = {fl: {"E": E1, "nu": 0.0, "alpha": a1, "Tref": TREF}, fr: {"E": E2, "nu": 0.0, "alpha": a2, "Tref": TREF}}
    mat = material(nu=0.0, region_mats=rm)
    return pf.solve(t2.mesh, mat, [dict(s_) for s_ in walls2], [], thermal={"T": np.full(len(nd2), TREF + DT)})


L1 = L2 = W / 2
r = series(ALPHA, ALPHA)
want = -DT * ALPHA * (L1 + L2) / (L1 / E1 + L2 / E2)                      # force balance of the two halves in series
assert r["multi_material"] and np.allclose(r["sx"], want, rtol=1e-7), (r["sx"].min(), r["sx"].max(), want)
print("ok   two materials in series (nu = 0), held between walls: sigma = -dT alpha (L1 + L2) / (L1/E1 + L2/E2) = %.4g" % want)
A2 = 2.0 * ALPHA                                                           # the second material expands twice as much; nu = 0 keeps the section free of stress across
r = series(ALPHA, A2)
want = -DT * (ALPHA * L1 + A2 * L2) / (L1 / E1 + L2 / E2)
far = np.abs(np.repeat(cx2, 4) - W / 2) > 20.0                            # beyond one bar width from the joint the sideways mismatch of the two parts has mostly died away (what is left is under 1 %)
assert far.sum() > 100 and np.allclose(r["sx"][far], want, rtol=0.01), (r["sx"][far].min(), r["sx"][far].max(), want)
print("ok   different expansion coefficients in the two parts: more than a bar width from the joint sigma = -dT (alpha1 L1 + alpha2 L2) / (L1/E1 + L2/E2) = %.4g within 1 %%" % want)

# ------------------------------------------------------------------------------------------------------- 5. loads, errors, the nonlinear solver
try:
    run(PIN)
    assert False, "no load and no temperature must still be refused"
except pf.ModelError as ex:
    assert "No loads" in str(ex)
pull = [{"kind": "pressure", "p": -10.0, "targets": [right]}]                  # 10 MPa of tension on the right end
a = run(PIN, pull, thermal=heated())
b = run(PIN, pull)
c = run(PIN, thermal=heated())
du = a["u"] - (b["u"] + c["u"])
assert np.abs(du).max() < 1e-9, np.abs(du).max()                           # the problem is linear: the two loads add
print("ok   a thermal load adds to a mechanical one (superposition)")
try:
    run(PIN, thermal=heated(), alpha=None)
    assert False, "alpha is needed"
except pf.ModelError as ex:
    assert "expansion coefficient" in str(ex), str(ex)
print("ok   a material without alpha is refused, in words")
try:
    run(PIN, thermal={"T": np.zeros(3)})
    assert False
except pf.ModelError as ex:
    assert "temperature field" in str(ex)
nan = heated(); nan["T"][3] = np.nan
try:
    run(PIN, thermal=nan)
    assert False
except pf.ModelError as ex:
    assert "NaN" in str(ex)
mt = dict(material()); mt.pop("Tref")
r = pf.solve(t.mesh, mt, PIN, [], thermal=heated())
assert any("reference temperature" in n for n in r["notes"])               # a material that gives none is stress free at 20 degC, and the result says so
assert abs(r["u"][at(r, W, H), 0] - ALPHA * (TREF + DT - 293.15) * W) < 1e-9
r = run(PIN, thermal=heated(), nl_on=True, order=2)
assert r["solver"] == "linear" and any("does not include thermal strain" in n for n in r["notes"])
try:
    run(PIN, thermal=heated(), nl_on=True, lin_on=False, order=2)
    assert False
except pf.ModelError as ex:
    assert "thermal strain" in str(ex)
print("ok   a wrong field is refused; a missing reference temperature is 20 degC and says so; the nonlinear solver says it has no thermal strain")

# without a temperature the solver gives what it gave before
r0 = run(PIN, pull)
assert r0["thermal"] is None and not any("THERMAL" in n for n in r0["notes"])
print("OK")
