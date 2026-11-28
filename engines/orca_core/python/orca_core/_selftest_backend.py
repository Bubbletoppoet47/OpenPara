"""A stand-in for the engine, for the tests of everything around it (the worker, cancel, progress, crashes, the result tables).

It does not slice.  It reads the bounding box of each object and "prints" one rectangular outer wall and one sparse-infill line per layer of
0.2 mm, so that a result has the right shape and plausible numbers.  The job setting  _selftest  picks a behaviour:

    ok (default)  finish          slow       take about 2 s, reporting progress, and stop when asked
    hang          never finish, stops when asked (cancel flag)       deaf   never finish and ignores the cancel flag (only ending the process stops it)
    crash         end the process at once without saying anything (like a crash in C++)
    segfault      really crash (a read at address 0)
    config        raise ConfigError for the key  sparse_infill_density
    slice         raise SliceError for the first object      boom       raise an ordinary exception (a bug)
"""
import ctypes
import os
import time

import numpy as np

from . import errors
from .roles import role_id

LAYER = 0.2


def run(job, folder, progress, is_cancelled):
    mode = job["settings"].get("_selftest", "ok")
    progress(0, "start")
    if mode == "crash":
        os._exit(77)
    if mode == "segfault":
        ctypes.string_at(0)
    if mode == "config":
        raise errors.ConfigError("sparse_infill_density", "Sparse infill density must be between 0 % and 100 %.", job["objects"][0]["name"])
    if mode == "slice":
        raise errors.SliceError(job["objects"][0]["name"], "The object has no volume at layer 3.")
    if mode == "boom":
        raise RuntimeError("a bug")
    if mode in ("hang", "slow", "deaf"):
        with open(os.path.join(folder, "pid"), "w") as f:
            f.write(str(os.getpid()))
        end = time.monotonic() + (2.0 if mode == "slow" else 1e9)
        n = 0
        while time.monotonic() < end:
            if mode != "deaf" and is_cancelled():
                raise errors.Cancelled("Cancelled at step %d." % n)
            n += 1
            progress(min(99, n), "layer %d" % n)
            time.sleep(0.05)

    pts, start, role, width, height, mm3, layer, obj, layer_z = [], [0], [], [], [], [], [], [], []
    for oi, o in enumerate(job["objects"]):
        v = o["vertices"] @ o["transform"][:3, :3].T + o["transform"][:3, 3]
        lo, hi = v.min(axis=0), v.max(axis=0)
        nl = max(1, int(round((hi[2] - lo[2]) / LAYER)))
        for li in range(nl):
            z = lo[2] + (li + 1) * LAYER
            if oi == 0:
                layer_z.append(z)
            loop = [(lo[0], lo[1], z), (hi[0], lo[1], z), (hi[0], hi[1], z), (lo[0], hi[1], z), (lo[0], lo[1], z)]
            infill = [(lo[0] + 0.4, lo[1] + 0.4, z), (hi[0] - 0.4, hi[1] - 0.4, z)]
            for pl, r, w in ((loop, "Outer wall", 0.42), (infill, "Sparse infill", 0.45)):
                pts.extend(pl)
                start.append(len(pts))
                role.append(role_id(r)); width.append(w); height.append(LAYER); mm3.append(w * LAYER); layer.append(li); obj.append(oi)
        progress(50.0 * (oi + 1) / len(job["objects"]), "object %d" % oi)
    layer_z = np.array(layer_z, dtype=np.float32)
    paths = dict(points=np.array(pts, dtype=np.float32), start=np.array(start, dtype=np.int64), layer_z=layer_z,
                 col_role=role, col_width=width, col_height=height, col_mm3_per_mm=mm3, col_layer=layer, col_object=obj,
                 col_instance=np.zeros(len(role)), col_region=np.zeros(len(role)), col_extruder=np.zeros(len(role)),
                 col_order=np.arange(len(role)), col_overhang=np.zeros(len(role)), col_curve=np.zeros(len(role)),
                 col_z_contoured=np.zeros(len(role)))
    pos = np.array(pts, dtype=np.float32)
    seglen = np.r_[0.0, np.linalg.norm(np.diff(pos, axis=0), axis=1)]
    moves = dict(position=pos, role=np.repeat(role, np.diff(start)).astype(np.uint8), feedrate=np.full(len(pos), 60.0, dtype=np.float32),
                 time=np.cumsum(seglen / 60.0).astype(np.float32))
    gcode = os.path.join(folder, "plate_1.gcode")
    with open(gcode, "w") as f:
        f.write("; selftest backend: not a real slice\nG28\n")
        for p in pts[:5]:
            f.write("G1 X%.3f Y%.3f Z%.3f\n" % p)
    progress(100, "done")
    return {"gcode": gcode, "paths": paths, "moves": moves,
            "estimate": {"time_normal_s": float(moves["time"][-1]), "filament_mm3": [float(sum(np.array(mm3) * 1.0))], "toolchanges": 0,
                         "time_by_role_s": {"Outer wall": 1.0, "Sparse infill": 2.0}},
            "warnings": [{"level": "tip", "message": "This is the selftest backend.", "code": 0}],
            "record": {"orca_version": "selftest", "module_version": "0", "settings": dict(job["settings"]), "threads": job["threads"]}}
