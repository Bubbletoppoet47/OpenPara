"""orca_core result tables (plan 5.3): lengths and volumes against hand sums, parts of a result, save and load, and what is refused."""
import faulthandler; faulthandler.dump_traceback_later(60, exit=True)
import os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engines", "orca_core", "python"))
import orca_core as oc
from orca_core import roles

# ---- roles: Orca's 20, the names Orca writes in G-code
assert len(oc.ROLES) == 20 and oc.ROLES[2] == "Outer wall" and oc.ROLES[4] == "Sparse infill" and oc.ROLES[14] == "Support"
assert oc.role_id("Outer wall") == 2 and oc.role_name(2) == "Outer wall"
try:
    oc.role_id("outer wall"); raise SystemExit("a wrong role name was accepted")
except KeyError as e:
    assert "Outer wall" in str(e)

# ---- a hand-made set of paths: 4 paths on 2 layers, 2 objects
#   path 0: (0,0,.2)->(3,0,.2)->(3,4,.2)      length 3 + 4 = 7        role Outer wall   layer 0 object 0  mm3_per_mm 0.1
#   path 1: (0,0,.2)->(10,0,.2)               length 10               role Sparse       layer 0 object 1  0.05
#   path 2: (1,1,.4)                          one point: length 0     role Inner wall   layer 1 object 0  0.1
#   path 3: (0,0,.4)->(0,0,.6)->(0,5,.6)      length .2 + 5 = 5.2     role Outer wall   layer 1 object 1  0.1
pts = [(0, 0, .2), (3, 0, .2), (3, 4, .2), (0, 0, .2), (10, 0, .2), (1, 1, .4), (0, 0, .4), (0, 0, .6), (0, 5, .6)]
start = [0, 3, 5, 6, 9]
P = oc.Paths.from_columns(pts, start, [0.2, 0.4], role=[2, 4, 1, 2], width=[.4] * 4, height=[.2] * 4, mm3_per_mm=[.1, .05, .1, .1],
                          layer=[0, 0, 1, 1], object=[0, 1, 0, 1])
assert len(P) == 4 and P.n_layers == 2 and np.array_equal(P.order, [0, 1, 2, 3]), "order defaults to the row number"
assert np.allclose(P.lengths(), [7, 10, 0, 5.2], atol=1e-5), P.lengths()
assert np.allclose(P.volumes(), [0.7, 0.5, 0, 0.52], atol=1e-5)
br = P.by_role()
assert set(br) == {"Outer wall", "Sparse infill", "Inner wall"} and abs(br["Outer wall"][0] - 12.2) < 1e-5 and abs(br["Outer wall"][1] - 1.22) < 1e-5, br
assert np.array_equal(P.path(1), np.array(pts[3:5], dtype=np.float32)) and len(P.path(2)) == 1

# parts: copies that are themselves consistent paths tables
L1 = P.layer_slice(1)
assert len(L1) == 2 and np.allclose(L1.lengths(), [0, 5.2], atol=1e-5) and np.array_equal(L1.start, [0, 1, 4]) and np.array_equal(L1.layer, [1, 1])
O1 = P.object_slice(1)
assert len(O1) == 2 and np.allclose(O1.lengths(), [10, 5.2], atol=1e-5) and np.array_equal(O1.points[:2], P.points[3:5])
W = P.role_slice("Outer wall")
assert len(W) == 2 and np.allclose(W.lengths(), [7, 5.2], atol=1e-5)
assert len(P.role_slice(oc.role_id("Sparse infill"), "Inner wall")) == 2
assert len(P.select(np.array([3, 0]))) == 2 and np.allclose(P.select(np.array([3, 0])).lengths(), [5.2, 7], atol=1e-5), "order as asked"
assert len(P.select(np.zeros(4, bool))) == 0 and len(oc.Paths.empty()) == 0 and oc.Paths.empty().lengths().shape == (0,)
Pc = P.layer_slice(0); Pc.points[:] = 99
assert P.points.max() < 99, "a slice is a copy"

# ---- refusals say what is wrong
def refused(f, *words):
    try:
        f()
    except ValueError as e:
        for w in words:
            assert w in str(e), (w, str(e))
        return
    raise SystemExit("not refused: %s" % (words,))
refused(lambda: oc.Paths.from_columns(pts, [0, 3, 5, 6, 8], [0.2, 0.4], role=[2] * 4, width=[1] * 4, height=[1] * 4, mm3_per_mm=[1] * 4, layer=[0] * 4, object=[0] * 4), "start")
refused(lambda: oc.Paths.from_columns(pts, start, [0.2, 0.4], role=[2] * 3, width=[1] * 4, height=[1] * 4, mm3_per_mm=[1] * 4, layer=[0] * 4, object=[0] * 4), "role", "rows")
refused(lambda: oc.Paths.from_columns(pts, start, [0.2, 0.4], role=[20] * 4, width=[1] * 4, height=[1] * 4, mm3_per_mm=[1] * 4, layer=[0] * 4, object=[0] * 4), "role")
refused(lambda: oc.Paths.from_columns(pts, start, [0.2], role=[2] * 4, width=[1] * 4, height=[1] * 4, mm3_per_mm=[1] * 4, layer=[0, 0, 1, 1], object=[0] * 4), "layer")
refused(lambda: oc.Paths.from_columns(pts, start, [0.2, 0.4], role=[2] * 4, width=[1] * 4), "missing")
refused(lambda: oc.Paths.from_columns(pts, start, [0.2, 0.4], role=[2] * 4, width=[1] * 4, height=[1] * 4, mm3_per_mm=[1] * 4, layer=[0] * 4, object=[0] * 4, colour=[1] * 4), "unknown")
refused(lambda: oc.Moves(role=[1]), "position")
refused(lambda: oc.Moves(position=np.zeros((3, 3)), feedrate=[1, 2]), "feedrate")

# ---- save and load: everything comes back, the G-code is copied
M = oc.Moves(position=np.arange(18, dtype=np.float32).reshape(6, 3), role=np.arange(6, dtype=np.uint8), feedrate=np.full(6, 50, np.float32),
             time=np.linspace(0, 5, 6).astype(np.float32))
tmp = tempfile.mkdtemp()
g = os.path.join(tmp, "src", "plate_1.gcode"); os.makedirs(os.path.dirname(g)); open(g, "w").write("G28\n")
E = oc.Estimate(time_normal_s=3600.5, filament_mm=[1200.0], filament_g=[3.5], toolchanges=0, time_by_role_s={"Outer wall": 100.0})
W_ = [oc.SliceWarning("warning", "A thin wall will not print.", 12, [1.5], "cube")]
R = oc.Result(g, P, M, E, W_, {"orca_version": "2.5.2", "settings": {"wall_loops": "3"}, "threads": 2})
out = os.path.join(tmp, "res")
R.save(out)
R2 = oc.Result.load(out)
assert open(R2.gcode_path).read() == "G28\n" and os.path.dirname(R2.gcode_path) == out
for k in P.columns:
    assert np.array_equal(R2.paths.columns[k], P.columns[k]) and R2.paths.columns[k].dtype == P.columns[k].dtype, k
assert np.array_equal(R2.paths.points, P.points) and np.array_equal(R2.paths.start, P.start) and np.array_equal(R2.paths.layer_z, P.layer_z)
assert np.array_equal(R2.moves["time"], M["time"]) and len(R2.moves) == 6 and "feedrate" in R2.moves
assert R2.estimate == E and R2.warnings == W_ and R2.record == R.record
assert not os.path.exists(os.path.join(out, "meta.json.tmp"))
print("orca_core results: ok")
