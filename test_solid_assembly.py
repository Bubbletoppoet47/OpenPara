"""3D FEA, big models: the stiffness matrix is added up from the chunks of elements in a short stack (not `K + part` after every chunk), with 32-bit indices, and
a model that cannot fit in the free memory is refused at once, in words, before any work is done.

Model (no window): the stack sum equals the plain sum; the assembled matrix of a mesh of many chunks equals the one added up the plain way, is symmetric and has
32-bit indices; the memory estimate, the ceiling (the most unknowns that fit) and the refusal; a solve with too little memory is refused before it assembles.
python test_solid_assembly.py"""
import faulthandler
faulthandler.dump_traceback_later(285, exit=True)
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "shared")]
import numpy as np
import scipy.sparse as sp
import build123d as b
import solid_geom as sg, solid_fem as fem, solid_model as sm

FAILS = []


def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------------------------------------ the stack sum
rng = np.random.default_rng(3)
parts = []
for k in range(37):
    m = sp.random(300, 300, density=0.02 + 0.03 * rng.random(), random_state=int(rng.integers(1 << 30)), format="csr")
    parts.append(m)
acc = fem._Sum()
depth = 0
for m in parts:
    acc.add(m)
    depth = max(depth, len(acc.stack))
plain = parts[0]
for m in parts[1:]:
    plain = plain + m
tot = acc.total()
ok(abs(tot - plain).max() < 1e-12, f"the stack sum of {len(parts)} parts equals the plain sum")
ok(depth <= 8, f"the stack stays short ({depth} matrices at most for {len(parts)} parts)")
ok(fem._Sum().total() is None, "no parts, no matrix")

# ------------------------------------------------------------------------------------------------ a mesh of many chunks
g = sg.analyze(b.Box(60, 30, 30))
raw = fem.mesh_solid(g, 2.6)
q = fem.quadratic(raw)
ne = len(q["conn"])
ok(ne > 3 * 4000, f"the test mesh has more than three chunks of elements ({ne:,})")
K, D = fem.assemble(q["nodes"], q["conn"], 200000.0, 0.3)


class Plain:
    """The old way, for the comparison: add every part to the running sum."""

    def __init__(self):
        self.m = None

    def add(self, x):
        self.m = x if self.m is None else self.m + x

    def total(self):
        return self.m


real = fem._Sum
fem._Sum = Plain
try:
    K2, _ = fem.assemble(q["nodes"], q["conn"], 200000.0, 0.3)
finally:
    fem._Sum = real
ok(abs(K - K2).max() <= 1e-9 * abs(K2).max(), f"the matrix of {ne:,} elements equals the one added up the plain way")
ok(abs(K - K.T).max() <= 1e-9 * abs(K).max(), "and it is symmetric")
ok(K.indices.dtype == np.int32 and K.indptr.dtype == np.int32, f"and its indices are 32-bit ({K.indices.dtype}, {K.nnz:,} entries)")
rigid = np.zeros(K.shape[0])
rigid[0::3] = 1.0
ok(np.abs(K @ rigid).max() < 1e-6 * abs(K).max(), "a rigid translation produces no force")

# ------------------------------------------------------------------------------------------------ memory
free = fem.available_memory()
ok(free is None or free > 1e7, f"the free memory can be told on this computer: {None if free is None else round(free / 1e9, 1)} GB")
ok(abs(fem.memory_estimate(725000) / 1e9 - 4.3) < 0.2, f"the estimate for the largest model measured (725,000 unknowns, 3.6 GB measured): {fem.memory_estimate(725000) / 1e9:.1f} GB")
ok(fem.memory_estimate(3e5) < fem.memory_estimate(6e5), "a larger model needs more")
real_avail0 = fem.available_memory
fem.available_memory = lambda: None
try:
    fem.check_memory(1e9)
    ok(fem.memory_ceiling() is None, "when the free memory cannot be told nothing is refused, and there is no ceiling")
finally:
    fem.available_memory = real_avail0
fem.check_memory(1000, free=4e9)
ok(True, "a small model in 4 GB is fine")
try:
    fem.check_memory(2e6, free=8e9)
    ok(False, "2 million unknowns in 8 GB must be refused")
except fem.FemError as ex:
    msg = str(ex)
    ok("2,000,000 unknowns" in msg and "GB" in msg and "larger elements" in msg and "converge" not in msg, f"refused in words with the sizes: {msg}")
c = fem.memory_ceiling(free=8e9)
ok(fem.memory_estimate(c) <= fem.MEM_SHARE * 8e9 < fem.memory_estimate(c + 2000), f"the ceiling for 8 GB is {c:,} unknowns, the largest that fits")
ok(fem.memory_ceiling(free=1e8) == 0, "a computer with almost nothing free has a ceiling of zero")

# solve() refuses before it assembles
gp = sg.analyze(b.Box(40, 20, 20))
fid = lambda ax, sd: next(f["id"] for f in gp["faces"] if np.dot(f["normal"], np.eye(3)[ax] * sd) > 0.99)
st = sm.default_setup()
st["h"] = 5.0
st["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(gp, fid(0, -1))]}]
st["loads"] = [{"kind": "force", "faces": [sg.face_sig(gp, fid(0, 1))], "f": [1000.0, 0.0, 0.0]}]
r0 = sm.run(gp, sm.resolve(gp, st), {})
ok(r0["info"]["solver"] == "direct", f"the small bar solves with the real free memory ({r0['info']['unknowns']:,} unknowns)")
calls = []
real_assemble, real_avail = fem.assemble, fem.available_memory
fem.assemble = lambda *a, **k: calls.append(1) or real_assemble(*a, **k)
fem.available_memory = lambda: 2.0e8
try:
    sm.run(gp, sm.resolve(gp, st), {})
    ok(False, "a solve with 0.2 GB free must be refused")
except fem.FemError as ex:
    ok("GB" in str(ex) and not calls, f"too little memory: refused before the matrix is built ({len(calls)} assemblies): {ex}")
finally:
    fem.assemble, fem.available_memory = real_assemble, real_avail

print("FAILED:" if FAILS else "OK solid assembly", FAILS or "")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
