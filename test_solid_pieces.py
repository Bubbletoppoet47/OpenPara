"""3D FEA: a part of several solids that are not joined (a compound) is several pieces.  A piece that no support holds is free to move: the solve is refused
at once, in words that name the piece, instead of failing in the solver ("singular" / "could not solve").  Pieces that all have their supports solve, each on
its own.   python test_solid_pieces.py"""
import faulthandler
faulthandler.dump_traceback_later(285, exit=True)
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


two = b.Compound([b.Pos(0, 0, 0) * b.Box(40, 20, 20), b.Pos(60, 0, 0) * b.Box(30, 20, 20)])
g = sg.analyze(two)
planes = [f for f in g["faces"] if f["kind"] == "plane"]


def face(x_min=None, x_max=None, nx=None):
    for f in planes:
        if np.dot(f["normal"], [1.0, 0, 0]) * nx > 0.99 and (x_min is None or f["center"][0] > x_min) and (x_max is None or f["center"][0] < x_max):
            return f["id"]


f_left = face(None, 0, -1)               # x = -20: the left face of the first box
f_mid1 = face(None, 30, 1)               # x = 20: the right face of the first box
f_mid2 = face(30, 70, -1)                # x = 45: the left face of the second box
f_right = face(70, None, 1)              # x = 75
ok(None not in (f_left, f_mid1, f_mid2, f_right), "the four end faces of the two boxes are found")
fs = lambda i: sg.face_sig(g, i)

# 1. only the first box is held: the second one floats
st = sm.default_setup()
st["h"] = 6.0
st["supports"] = [{"mode": "fixed", "faces": [fs(f_left)]}]
st["loads"] = [{"kind": "force", "faces": [fs(f_mid1)], "f": [1000.0, 0.0, 0.0]}]
try:
    sm.run(g, sm.resolve(g, st), {})
    ok(False, "a piece without a support must be refused")
except fem.FemError as ex:
    m = str(ex)
    ok("2 pieces" in m and "not joined" in m and "piece 2" in m and "30 x 20 x 20 mm" in m and "around x 60" in m and "assembly" in m,
       f"the floating piece is named in words: {m}")
    ok("singular" not in m and "could not solve" not in m and "converge" not in m, "and it is not the solver's own failure")

# 2. both boxes held (each on its own): it solves, piece by piece
st["supports"] = [{"mode": "fixed", "faces": [fs(f_left)]}, {"mode": "fixed", "faces": [fs(f_right)]}]
st["loads"] = [{"kind": "force", "faces": [fs(f_mid1)], "f": [1000.0, 0.0, 0.0]}, {"kind": "force", "faces": [fs(f_mid2)], "f": [-500.0, 0.0, 0.0]}]
r = sm.run(g, sm.resolve(g, st), {})
want1 = 1000.0 * 40.0 / (20 * 20 * 200000.0)
ok(r["equilibrium"] < 1e-6 and r["info"]["solver"] == "direct", f"each piece held on its own: solves, equilibrium {r['equilibrium']:.1e}")
ok(abs(r["reaction"][0] + 500.0) < 1.0, f"the reactions of the two supports add up to the two loads ({r['reaction'][0]:.2f} N against -500 N)")
ok(abs(r["umax"] - want1) / want1 < 0.1, f"the first box is pulled {r['umax']:.6f} mm (F L / A E = {want1:.6f} mm)")

# 3. one piece: the old messages are the same
one = sg.analyze(b.Box(40, 20, 20))
fid = next(f["id"] for f in one["faces"] if f["kind"] == "plane" and f["normal"][0] < -0.99)
s1 = sm.default_setup()
s1["h"] = 6.0
s1["supports"] = [{"mode": "slide", "faces": [sg.face_sig(one, fid)]}]
s1["loads"] = [{"kind": "force", "faces": [sg.face_sig(one, next(f["id"] for f in one["faces"] if f["kind"] == "plane" and f["normal"][0] > 0.99))], "f": [100.0, 0.0, 0.0]}]
try:
    sm.run(one, sm.resolve(one, s1), {})
    ok(False, "one slide support leaves the part free: refused")
except fem.FemError as ex:
    ok("free to move or turn" in str(ex) and "pieces" not in str(ex), f"a single piece keeps its message: {ex}")

# 4. the pieces of a mesh
q = fem.quadratic(fem.mesh_solid(g, 8.0))
lab, mm = fem.pieces(q["nodes"], q.get("groups") or q["conn"])
ok(mm == 2 and len(lab) == len(q["nodes"]) and set(np.unique(lab)) == {0, 1}, f"two boxes are two pieces ({mm})")
q1 = fem.quadratic(fem.mesh_solid(one, 8.0))
ok(fem.pieces(q1["nodes"], q1["conn"])[1] == 1, "one box is one piece")

print("FAILED:" if FAILS else "OK solid pieces", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
