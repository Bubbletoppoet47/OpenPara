"""3D FEA, large models: above fem.DIRECT_LIMIT unknowns the system is no longer factored (that needs far too much memory) but solved by conjugate gradients with an
algebraic-multigrid preconditioner (pyamg), whose iteration count hardly grows with the size.

Model (no window): the direct and the multigrid answer agree (also with bearing supports, which turn the unknowns of a node into a frame of its own); a bar with
more unknowns than the real direct limit matches beam theory; a missing pyamg and a stalled solver are refused in plain words that name the size; Cancel is
noticed between iterations; the stage names for the progress bar; the direct path (symmetric ordering) agrees with the general factorisation and still says
when a matrix is singular.   python test_solid_multigrid.py"""
import faulthandler
faulthandler.dump_traceback_later(285, exit=True)
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


REAL_LIMIT = fem.DIRECT_LIMIT
try:
    import pyamg
    HAVE = True
except ImportError:
    HAVE = False
ok(HAVE, "pyamg is installed (the add-on lists it under requires)")

# ------------------------------------------------------------------------------------------------ the direct path
n = 30
lap = sp.diags([-1, 2.01, -1], [-1, 0, 1], shape=(n * n, n * n)) + sp.diags([-1, -1], [-n, n], shape=(n * n, n * n))
lap = (lap + lap.T) / 2.0
lap = lap.tocsc()
rhs = np.arange(n * n, dtype=float) % 7 - 3.0
x_ref = spl.splu(lap).solve(rhs)
x, how = fem.solve_system(lap, rhs)
ok(how == "direct" and np.abs(x - x_ref).max() < 1e-9 * np.abs(x_ref).max(), f"the direct path (symmetric ordering) agrees with the general factorisation: {np.abs(x - x_ref).max():.1e}")
sing = sp.lil_matrix(lap.shape)
sing[0, 0] = 1.0
sing = sing.tocsc()
try:
    fem.solve_system(sing, rhs)
    ok(False, "a singular matrix must be refused")
except fem.FemError as ex:
    ok("singular" in str(ex), f"a singular matrix is still refused in plain words: {ex}")

# ------------------------------------------------------------------------------------------------ the multigrid path on a stand-in system
if HAVE:
    old = fem.DIRECT_LIMIT
    fem.DIRECT_LIMIT = 100
    try:
        x, how = fem.solve_system(lap, rhs)
        ok(how == "iterative" and np.abs(x - x_ref).max() < 1e-6 * np.abs(x_ref).max(), f"multigrid: {how}, the same answer to {np.abs(x - x_ref).max() / np.abs(x_ref).max():.1e}")
        class Bar:
            def __init__(self):
                self.stages, self.parts = [], []

            def __call__(self, text):
                pass

            def stage(self, key, size=0.0):
                self.stages.append(key)

            def part(self, fraction):
                self.parts.append(fraction)
        bar = Bar()
        fem.solve_system(lap, rhs, progress=bar)
        ok(bar.stages == ["ilu", "cg"] and len(bar.parts) >= 1 and all(0.0 <= f <= 1.0 for f in bar.parts),
           f"the progress bar hears of the preparation and then of the iterations ({bar.stages}), and how far the residual has fallen ({len(bar.parts)} reports, last {bar.parts[-1] if bar.parts else None})")
        calls = [0]

        def cancel():
            calls[0] += 1
            return calls[0] > 3
        try:
            fem.solve_system(lap, rhs, cancel=cancel)
            ok(False, "Cancel must stop the iterations")
        except fem.Cancelled:
            ok(True, "Cancel is noticed between the iterations")
        # a solver that stalls: refused in plain words, after one more try with other settings
        real_cg = fem.spl.cg
        tries = [0]

        def stalled(A, f, **k):
            tries[0] += 1
            return np.zeros(len(f)), 1
        fem.spl.cg = stalled
        try:
            fem.solve_system(lap, rhs)
            ok(False, "a stalled solver must be refused")
        except fem.FemError as ex:
            ok("could not solve" in str(ex) and "900 unknowns" in str(ex) and "converge" not in str(ex) and tries[0] == 2, f"a stall is refused after a second try, with the size and no 'larger element size' myth: {ex}")
        finally:
            fem.spl.cg = real_cg
        # pyamg missing
        real_amg = fem._amg
        fem._amg = lambda: None
        try:
            fem.solve_system(lap, rhs)
            ok(False, "no pyamg must be refused")
        except fem.FemError as ex:
            ok("pyamg" in str(ex) and "900 unknowns" in str(ex) and "100" in str(ex), f"no pyamg: {ex}")
        finally:
            fem._amg = real_amg
    finally:
        fem.DIRECT_LIMIT = old

# ------------------------------------------------------------------------------------------------ the same answer both ways, with bearing supports (frames)
plate = b.Box(80, 40, 12) - b.Pos(-25, 0, 0) * b.Cylinder(6, 12) - b.Pos(25, 0, 0) * b.Cylinder(6, 12)
gp = sg.analyze(plate)
holes = [f["id"] for f in sorted([f for f in gp["faces"] if f["kind"] == "cylinder"], key=lambda f: f["center"][0])]
topf = next(f["id"] for f in gp["faces"] if f["kind"] == "plane" and f["normal"][1] > 0.99)
st = sm.default_setup()
st["h"] = 4.0
st["supports"] = [{"mode": "bearing", "faces": [sg.face_sig(gp, f) for f in holes]}]
st["loads"] = [{"kind": "force", "faces": [sg.face_sig(gp, topf)], "f": [300.0, -2000.0, 150.0]}]
r_dir = sm.run(gp, sm.resolve(gp, st), {})
ok(r_dir["info"]["solver"] == "direct", f"bearing plate, direct: {r_dir['info']['unknowns']:,} unknowns")
if HAVE:
    fem.DIRECT_LIMIT = 500
    try:
        r_it = sm.run(gp, sm.resolve(gp, st), {})
    finally:
        fem.DIRECT_LIMIT = REAL_LIMIT
    du = np.abs(r_it["u"] - r_dir["u"]).max() / np.abs(r_dir["u"]).max()
    ok(r_it["info"]["solver"] == "iterative" and du < 1e-5, f"bearing plate, multigrid: the same displacements to {du:.1e}")
    ok(np.allclose(r_it["reaction"], r_dir["reaction"], rtol=1e-4, atol=1e-3) and r_it["equilibrium"] < 1e-6, f"and the same reaction {np.round(r_it['reaction'], 3).tolist()}, equilibrium {r_it['equilibrium']:.1e}")
    ok(abs(r_it["vm_max"] - r_dir["vm_max"]) < 1e-4 * r_dir["vm_max"], f"and the same peak stress {r_it['vm_max']:.3f} against {r_dir['vm_max']:.3f} MPa")

# ------------------------------------------------------------------------------------------------ a bar above the real limit: beam theory
if HAVE:
    solid = b.Solid.make_box(120, 24, 24)
    g = sg.analyze(solid)

    def face_at(axis, side):
        nv = np.zeros(3)
        nv[axis] = side
        return next(f["id"] for f in g["faces"] if np.dot(f["normal"], nv) > 0.99)
    s2 = sm.default_setup()
    s2["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, face_at(0, -1))]}]
    s2["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, face_at(0, 1))], "f": [20000.0, 0.0, 0.0]}]
    res = None
    for h in (3.0, 2.4, 2.0):
        s2["h"] = h
        t0 = time.time()
        res = sm.run(g, sm.resolve(g, s2), {})
        if res["info"]["unknowns"] > REAL_LIMIT:
            break
    want = 20000.0 * 120.0 / (24 * 24 * 200000.0)
    ok(res["info"]["unknowns"] > REAL_LIMIT and res["info"]["solver"] == "iterative", f"a bar of {res['info']['unknowns']:,} unknowns (the direct limit is {REAL_LIMIT:,}) goes to multigrid")
    ok(abs(res["umax"] - want) / want < 0.03, f"its elongation {res['umax']:.6f} mm against F L / (A E) = {want:.6f} mm")
    ok(res["equilibrium"] < 1e-6 and abs(res["reaction"][0] + 20000.0) < 0.5, f"equilibrium {res['equilibrium']:.1e}, reaction {res['reaction'][0]:.2f} N")
    ok(res["info"]["residual"] < 1e-6, f"the residual is {res['info']['residual']:.1e}; solved in {res['info']['seconds']:.1f} s")

print("FAILED:" if FAILS else "OK solid multigrid", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
