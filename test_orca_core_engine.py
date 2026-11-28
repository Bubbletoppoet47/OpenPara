"""orca_core with the compiled engine (SLC-2; plan chapter 11 tests T1 to T7 as far as they are about one part on one plate).

Needs the compiled module `_orca_core` (built from engines/orca_core): set ORCA_CORE_BUILD_DIR to the build folder that holds it, and
ORCA_CORE_RESOURCES to Orca's `resources` folder if you have one. Without the module this test says so and passes: a copy of OpenPara
that has no engine is a normal copy.

What it checks, with the real engine: a slice gives the layers, paths, moves and estimate that agree with each other and with the G-code file
Orca wrote; progress comes in order; settings that cannot work come back as ConfigError with the key; a setting on one object changes that
object; two objects are both printed; a cancel stops a long slice; a mesh with no thickness is a SliceError in words; the engine's own record
(version, commit, settings, mesh hashes) is in the result."""
import faulthandler; faulthandler.dump_traceback_later(280, exit=True)
import os, re, sys, threading, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engines", "orca_core", "python"))
import orca_core as oc
from orca_core import errors
from orca_core import _engine

try:
    _engine._core()
except errors.EngineMissing:
    print("orca_core engine: skipped (the compiled engine is not built here; set ORCA_CORE_BUILD_DIR to test it)")
    sys.exit(0)


def cube(size, at=(0.0, 0.0)):
    v = np.array([(x, y, z) for z in (0, size) for y in (0, size) for x in (0, size)], float) + [at[0], at[1], 0.0]
    f = np.array([t for a, b, c, d in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)) for t in ((a, b, c), (a, c, d))])
    return v, f


BASE = {"layer_change_gcode": "G92 E0"}


def run(settings, objects, **kw):
    j = oc.Job(dict(BASE, **settings), threads=2)
    for o in objects:
        j.add_object(o[0], o[1], name=o[2], settings=o[3] if len(o) > 3 else None)
    return j.slice(**kw)


# ---- 1. one cube: layers, paths, moves, estimate and the G-code file agree
v, f = cube(20, (100, 100))
seen = []
r = run({}, [(v, f, "cube")], progress=lambda p, m: seen.append((p, m)))
assert r.paths.n_layers == 100, r.paths.n_layers                       # 20 mm at 0.2 mm
assert abs(r.paths.layer_z[0] - 0.2) < 1e-4 and abs(r.paths.layer_z[-1] - 20.0) < 1e-3, r.paths.layer_z[[0, -1]]
roles = r.paths.by_role()
for want in ("Outer wall", "Inner wall", "Sparse infill", "Top surface", "Bottom surface"):
    assert want in roles, (want, sorted(roles))
part = r.paths.select(np.isin(r.paths.role, [oc.role_id(n) for n in ("Outer wall", "Inner wall", "Sparse infill", "Internal solid infill", "Top surface",
                                                                         "Bottom surface", "Bridge", "Internal Bridge", "Gap infill")]))
# the part's own paths lie over the cube (the skirt and the like are outside it)
inside = (part.points[:, 0] > 99.5) & (part.points[:, 0] < 120.5) & (part.points[:, 1] > 99.5) & (part.points[:, 1] < 120.5)
assert inside.all(), "part paths outside the cube"
assert abs(part.points[:, 2].max() - 20.0) < 1e-3 and abs(part.points[:, 2].min() - 0.2) < 1e-3
# the volume of the paths is the volume Orca's G-code extrudes while it moves (extrusion with x/y movement, after the first layer change)
text = open(r.gcode_path, encoding="utf-8").read().split("\n")
first = next(i for i, l in enumerate(text) if l.startswith(";LAYER_CHANGE"))
extruded_mm = 0.0
for l in text[first:]:
    if l.startswith(("G1 ", "G2 ", "G3 ")) and re.search(r" [XY]", l):
        m = re.search(r" E(-?[0-9.]+)", l)
        if m and float(m.group(1)) > 0:
            extruded_mm += float(m.group(1))
fil_d = float(r.record["settings"]["filament_diameter"].split(",")[0].split(";")[0])
got = r.paths.select(r.paths.role != oc.role_id("Custom")).volumes().sum()
want = extruded_mm * np.pi * fil_d ** 2 / 4
assert abs(got - want) < 0.002 * want, "paths %.1f mm3 against the G-code's %.1f mm3" % (got, want)
# the estimate: time is the sum of the moves, the plastic is what Orca's own header says
assert r.estimate.time_normal_s > 60 and abs(r.moves["time"].sum() - r.estimate.time_normal_s) < 0.01 * r.estimate.time_normal_s
hdr = {m.group(1): float(m.group(2)) for l in text if (m := re.match(r"; filament used \[(mm|cm3)\] = ([0-9.]+)", l))}
assert abs(r.estimate.filament_mm[0] - hdr["mm"]) < 0.01 * hdr["mm"] + 0.01 and abs(r.estimate.filament_mm3[0] / 1000 - hdr["cm3"]) < 0.01, (r.estimate, hdr)
assert len(r.moves) > len(r.paths) and "feedrate" in r.moves and r.moves["feedrate"].max() > 10
assert int((r.moves["type"] == 10).sum()) >= len(r.paths)               # a path is a run of extrusion moves
# progress: in order, with Orca's own words, from the start of slicing to the end of the G-code
pcts = [p for p, _ in seen]
assert pcts == sorted(pcts) and pcts[0] <= 5 and pcts[-1] == 100 and any("walls" in m.lower() for _, m in seen), seen[:3]
# the record
rec = r.record
assert rec["orca_version"] == "2.5.2" and len(rec["orca_commit"]) == 40 and rec["threads"] == 2
assert len(rec["mesh_hashes"]) == 1 and len(rec["mesh_hashes"][0]) == 64 and rec["settings"]["layer_change_gcode"] == "G92 E0"
assert rec["object_names"] == ["cube"]
# a result can be saved and read back
import tempfile
d = tempfile.mkdtemp()
r.save(d)
r2 = oc.Result.load(d)
assert len(r2.paths) == len(r.paths) and np.array_equal(r2.paths.points, r.paths.points) and r2.estimate.time_normal_s == r.estimate.time_normal_s
print("one cube: %d layers, %d paths, %d moves, %.0f s" % (r.paths.n_layers, len(r.paths), len(r.moves), r.estimate.time_normal_s))

# ---- 2. settings: a value that cannot be read, settings that cannot work together, a setting on one object
e = None
try:
    run({"wall_loops": "abc"}, [(v, f, "cube")])
except errors.ConfigError as ex:
    e = ex
assert e is not None and e.key == "wall_loops" and "abc" in str(e), e
for settings, key in (({"layer_height": "5"}, "layer_height"), ({"line_width": "9"}, "line_width")):
    try:
        run(settings, [(v, f, "cube")])
        raise SystemExit("settings that cannot work were accepted: %s" % settings)
    except errors.ConfigError as ex:
        assert ex.key == key and len(str(ex)) > 10, (ex.key, str(ex))
a = run({}, [(v, f, "cube")]).paths.by_role()["Inner wall"][0]
b = run({}, [(v, f, "cube", {"wall_loops": "5"})]).paths.by_role()["Inner wall"][0]
assert b > 2.5 * a, "five walls on the object should give far more inner wall than the default two (%.0f -> %.0f mm)" % (a, b)
try:
    run({}, [(v, f, "cube", {"wall_loops": "many"})])
    raise SystemExit("a bad value on an object was accepted")
except errors.ConfigError as ex:
    assert ex.object == "cube" and ex.key == "wall_loops", (ex.object, ex.key)

# ---- 3. two objects are both printed (and a transform places them)
v2, f2 = cube(10, (140, 100))
r = run({}, [(v, f, "a"), (v2, f2, "b")])
x = r.paths.select(np.isin(r.paths.role, [oc.role_id("Outer wall")])).points[:, 0]
assert (x < 121).any() and (x > 139).any(), "both objects are printed"
T = np.eye(4); T[:3, 3] = (30.0, 40.0, 0.0)
v0, f0 = cube(20, (0, 0))
j = oc.Job(BASE, threads=2); j.add_object(v0, f0, "moved", transform=T)
rm = j.slice()
w = rm.paths.select(rm.paths.role == oc.role_id("Outer wall")).points
assert abs(w[:, 0].min() - 30) < 0.5 and abs(w[:, 0].max() - 50) < 0.5 and abs(w[:, 1].min() - 40) < 0.5, (w.min(0), w.max(0))

# ---- 4. a mesh with no thickness
vf = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], float)
try:
    run({}, [(vf, np.array([[0, 1, 2], [0, 2, 3]]), "flat")])
    raise SystemExit("a flat mesh was sliced")
except errors.SliceError as ex:
    assert "layers" in str(ex).lower() or "thick" in str(ex).lower(), str(ex)

# ---- 5. cancel: a long slice stops soon after the cancel
vb, fb = cube(100, (60, 60))
ev = threading.Event()
t0 = time.time()
try:
    run({"layer_height": "0.1"}, [(vb, fb, "big")], progress=lambda p, m: ev.set() if p >= 15 else None, cancel=ev)
    raise SystemExit("the slice was not cancelled")
except errors.Cancelled:
    pass
assert time.time() - t0 < 30

# ---- 6. several slices one after another leave nothing behind
import glob
before = set(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*")))
run({}, [(v, f, "cube")])
assert set(glob.glob(os.path.join(tempfile.gettempdir(), "orca_job_*"))) == before

print("orca_core engine: ok")
