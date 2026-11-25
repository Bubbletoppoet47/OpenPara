"""The 2D thermal solver's exchange with a flowing fluid (kind 'fluid': h and the fluid temperature are functions of the point on the edge): against the plain convection
condition it generalises, against closed forms with a coefficient that changes along the edge, against the heat balance, and with the functions given the points in the
sketch units (not metres).  The mutations at the end must fail.
python test_thermal_fluid.py"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "thermal2d"), os.path.join(HERE, "shared")]
import numpy as np

import thermal_fem as tf

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def rect_mesh(W, H, nx, ny):
    """A structured mesh of [0, W] x [0, H] in the format of physics_geom.mesh_faces.  Sides: ln 0 bottom, ln 1 right, ln 2 top, ln 3 left."""
    xs, ys = np.linspace(0, W, nx + 1), np.linspace(0, H, ny + 1)
    nodes = np.array([(x, y) for y in ys for x in xs])
    idx = lambda i, j: j * (nx + 1) + i
    tris = []
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
            tris += [(a, b, c), (a, c, d)]
    segs = {("ln", 0): [(idx(i, 0), idx(i + 1, 0)) for i in range(nx)], ("ln", 1): [(idx(nx, j), idx(nx, j + 1)) for j in range(ny)],
            ("ln", 2): [(idx(i + 1, ny), idx(i, ny)) for i in range(nx)], ("ln", 3): [(idx(0, j + 1), idx(0, j)) for j in range(ny)]}
    return {"nodes": nodes, "tris": np.array(tris), "tri_face": np.zeros(len(tris), dtype=np.int64), "curve_segs": segs,
            "point_node": {0: idx(0, 0), 1: idx(nx, 0), 2: idx(nx, ny), 3: idx(0, ny)}}


def setup(k=400.0, lscale=1.0, order=2, **kw):
    s = {"lscale": lscale, "t": 1.0, "order": order, "mat": {"k": k, "rho": 8000.0, "cp": 400.0}, "analysis": "steady", "conds": []}
    s.update(kw)
    return s


def solve(mesh, conds, **kw):
    return tf.solve(mesh, setup(conds=conds, **kw))


def flow_of(r, kind):
    return sum(f["Q"] for f in r["flows"] if f["kind"] == kind)


# ------------------------------------------------------------------------------------------------------------ 1. constant h and T_inf = the convection condition
mesh = rect_mesh(0.1, 0.02, 20, 4)
left = {"kind": "temp", "T": 400.0, "targets": [("ln", 3)], "name": "hot"}
conv = {"kind": "conv", "h": 35.0, "Tinf": 290.0, "targets": [("ln", 1)], "name": "conv"}
fl = {"kind": "fluid", "h": lambda p: np.full(len(p), 35.0), "Tinf": lambda p: np.full(len(p), 290.0), "targets": [("ln", 1)], "name": "fluid"}
fl_const = {"kind": "fluid", "h": 35.0, "Tinf": 290.0, "targets": [("ln", 1)], "name": "fluid constants"}
for order in (1, 2):
    a = solve(mesh, [left, conv], order=order)
    b = solve(mesh, [left, fl], order=order)
    c = solve(mesh, [left, fl_const], order=order)
    ok(np.abs(a["T"] - b["T"]).max() < 1e-9 and np.abs(a["T"] - c["T"]).max() < 1e-9,
       f"order {order}: a fluid exchange with a constant coefficient and temperature gives the convection result to {np.abs(a['T'] - b['T']).max():.1e} K")
    ok(abs(flow_of(a, "conv") - flow_of(b, "fluid")) < 1e-9 * abs(flow_of(a, "conv")), f"order {order}: and the same heat flow ({flow_of(b, 'fluid'):.6g} W)")
    ok(b["balance"]["relative_error"] < 1e-9, f"order {order}: and the heat balance closes ({b['balance']['relative_error']:.1e})")

# ------------------------------------------------------------------------------------------------------------ 2. a coefficient that changes along the edge
# a body so conductive that it is at one temperature: the heat to the fluid is the integral of h (T_s - T_inf) along the edge, in closed form
H = 0.02
mesh = rect_mesh(0.05, H, 10, 8)
Ts, Tinf = 360.0, 300.0
hfun = lambda p: 20.0 + 2000.0 * p[:, 1]                                       # W/(m2 K), p in metres here (lscale 1): 20 .. 60 along the edge
r = solve(mesh, [{"kind": "temp", "T": Ts, "targets": [("ln", 3)], "name": "hot"},
                 {"kind": "fluid", "h": hfun, "Tinf": lambda p: np.full(len(p), Tinf), "targets": [("ln", 1)], "name": "fluid"}], k=1.0e7)
Q_exact = (20.0 * H + 1000.0 * H * H) * (Ts - Tinf)
Qf = -flow_of(r, "fluid")
ok(abs(Qf - Q_exact) < 2e-4 * Q_exact, f"a very conductive body: the heat to the fluid is the integral of h along the edge ({Qf:.6g} W against {Q_exact:.6g} W)")
ok(r["balance"]["relative_error"] < 1e-5, f"and the heat balance closes ({r['balance']['relative_error']:.1e}; the conductivity of 1e7 W/(m K) limits the matrix conditioning)")
ok(abs(r["flows"][0]["Q"] - Qf) < 1e-6 * Qf or abs(flow_of(r, "temp") - Qf) < 1e-6 * Qf, f"the heat that the fixed temperature feeds in is the heat the fluid takes ({flow_of(r, 'temp'):.6g} W)")

# the fluid temperature that changes along the edge: the same closed form
Tfun = lambda p: 280.0 + 4000.0 * p[:, 1]                                     # 280 .. 360 K
r = solve(mesh, [{"kind": "temp", "T": 360.0, "targets": [("ln", 3)], "name": "hot"},
                 {"kind": "fluid", "h": lambda p: np.full(len(p), 40.0), "Tinf": Tfun, "targets": [("ln", 1)], "name": "fluid"}], k=1.0e7)
Q_exact = 40.0 * (360.0 * H - (280.0 * H + 2000.0 * H * H))
Qf = -flow_of(r, "fluid")
ok(abs(Qf - Q_exact) < 2e-4 * Q_exact, f"and a fluid temperature that changes along the edge ({Qf:.6g} W against {Q_exact:.6g} W)")

# ------------------------------------------------------------------------------------------------------------ 3. the points are given in sketch units
seen = []


def spy(p):
    seen.append(np.array(p, float))
    return np.full(len(p), 25.0)


mesh_mm = rect_mesh(50.0, 20.0, 10, 4)                                          # millimetres
r = solve(mesh_mm, [{"kind": "temp", "T": 350.0, "targets": [("ln", 3)], "name": "hot"},
                    {"kind": "fluid", "h": spy, "Tinf": lambda p: np.full(len(p), 300.0), "targets": [("ln", 1)], "name": "fluid"}], lscale=1.0e-3, k=1.0e7)
pts = np.vstack(seen)
ok(abs(pts[:, 0].min() - 50.0) < 1e-9 and abs(pts[:, 0].max() - 50.0) < 1e-9 and 0.0 < pts[:, 1].min() and pts[:, 1].max() < 20.0,
   f"the functions get the points of the edge in the sketch units (x = 50 mm, y between {pts[:, 1].min():.2f} and {pts[:, 1].max():.2f} mm)")
Qf = -flow_of(r, "fluid")
ok(abs(Qf - 25.0 * 0.020 * 50.0) < 2e-4 * 25.0 * 0.020 * 50.0, f"and the heat is right in watts ({Qf:.6g} W)")

# a linearised exchange (Coupled Physics iterates q = h (T - Tref)): its reference is not a temperature, so it may be below 0 K; the same thing is refused without the flag
r = solve(mesh, [{"kind": "temp", "T": Ts, "targets": [("ln", 3)], "name": "hot"},
                 {"kind": "fluid", "h": 40.0, "Tinf": -150.0, "linearised": True, "targets": [("ln", 1)], "name": "linearised"}], k=1.0e7)
Q_exact = 40.0 * H * (Ts + 150.0)
ok(abs(-flow_of(r, "fluid") - Q_exact) < 2e-4 * Q_exact, f"a linearised exchange takes a reference below 0 K: the heat is h (T - Tref) A ({-flow_of(r, 'fluid'):.6g} W against {Q_exact:.6g} W)")
try:
    solve(mesh, [left, {"kind": "fluid", "h": 40.0, "Tinf": -150.0, "targets": [("ln", 1)], "name": "x"}])
    ok(False, "a reference below 0 K is refused when the exchange is not linearised")
except tf.ModelError as ex:
    ok("above 0 K" in str(ex), "and the same reference is refused when the exchange is a real fluid temperature")

# ------------------------------------------------------------------------------------------------------------ 4. refusals in words
for bad, what in ((lambda p: np.full(len(p), -1.0), "a coefficient"), (lambda p: np.full(len(p), np.nan), "a coefficient")):
    try:
        solve(mesh, [left, {"kind": "fluid", "h": bad, "Tinf": 290.0, "targets": [("ln", 1)], "name": "x"}])
        ok(False, "a negative or missing coefficient is refused")
    except tf.ModelError as ex:
        ok("coefficient" in str(ex), f"a bad coefficient is refused: {ex}")
try:
    solve(mesh, [left, {"kind": "fluid", "h": 10.0, "Tinf": lambda p: np.zeros(len(p)), "targets": [("ln", 1)], "name": "x"}])
    ok(False, "a fluid temperature of 0 K is refused")
except tf.ModelError as ex:
    ok("above 0 K" in str(ex), "a fluid temperature of 0 K is refused")
try:
    solve(mesh, [{"kind": "fluid", "h": 0.0, "Tinf": 290.0, "targets": [("ln", 1)], "name": "x"}])
    ok(False, "a body with only a zero-coefficient fluid edge is not tied to a temperature")
except tf.ModelError as ex:
    ok("temperature, convection or radiation" in str(ex) or "singular" in str(ex), "a body tied to nothing by a zero coefficient is refused as before")

# ------------------------------------------------------------------------------------------------------------ 5. mutation: if the coefficient is ignored the closed form fails
orig = tf.np.einsum
calls = []


def broken(sub, *ops, **kw):
    if sub == "e,g,eg,gi,gj->eij":
        ops = list(ops)
        ops[2] = np.zeros_like(ops[2])
        calls.append(1)
    return orig(sub, *ops, **kw)


tf.np.einsum = broken
try:
    r = solve(mesh, [{"kind": "temp", "T": Ts, "targets": [("ln", 3)], "name": "hot"},
                     {"kind": "fluid", "h": hfun, "Tinf": lambda p: np.full(len(p), Tinf), "targets": [("ln", 1)], "name": "fluid"}], k=1.0e7)
    ok(calls and abs(-flow_of(r, "fluid") - (20.0 * H + 1000.0 * H * H) * (Ts - Tinf)) > 0.05 * (20.0 * H) * (Ts - Tinf) or r["balance"]["relative_error"] > 1e-6,
       "mutation: with the coefficient left out of the matrix the closed form or the balance fails (the check can fail)")
except tf.ModelError:
    ok(True, "mutation: with the coefficient left out the solve refuses (the check can fail)")
finally:
    tf.np.einsum = orig

print()
if FAILS:
    print(f"{len(FAILS)} FAILED")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("OK thermal fluid")
