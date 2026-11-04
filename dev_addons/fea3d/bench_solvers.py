"""Run this on YOUR machine: python bench_solvers.py [grid size, default 48] [--threads N]

It builds a test body (a block with spherical holes), solves one compression test with every solver, and prints how many cores
are there, which packages are installed, and the time of each solver.  With your own model: edit `occ` below (a 3D boolean numpy array)."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))); import boot  # noqa: E402  (shared/, core/ and the add-on folders)
import os
import sys
import time

import numpy as np

import voxel as VX

n = int(next((a for a in sys.argv[1:] if a.isdigit()), 48))
if "--threads" in sys.argv:
    os.environ["NUMBA_NUM_THREADS"] = sys.argv[sys.argv.index("--threads") + 1]

print(f"logical cores seen by Python: {os.cpu_count()}")
for name in ("numba", "pypardiso", "pyamg", "scipy", "numpy"):
    try:
        mod = __import__(name)
        print(f"  {name:10s} {getattr(mod, '__version__', 'installed')}")
    except Exception:
        print(f"  {name:10s} NOT installed")
try:
    import gmg
    print(f"  Numba threads used: {gmg.threads()}")
except Exception as ex:
    print("  (parallel multigrid unavailable:", ex, ")")

rng = np.random.default_rng(1)
g = np.indices((n,) * 3).transpose(1, 2, 3, 0).astype(float)
occ = np.ones((n,) * 3, bool)
for _ in range(14):
    c = rng.uniform(0.15 * n, 0.85 * n, 3)
    r = rng.uniform(0.08 * n, 0.16 * n)
    occ &= ((g - c) ** 2).sum(-1) > r * r
print(f"\ntest body {n}^3 grid, {int(occ.sum())} solid elements, about {3 * int(occ.sum()) // 1} x 1.05 unknowns\n")
print(f"{'solver':34s} {'time':>8s} {'iterations':>11s} {'residual':>10s} {'E_app':>12s}")
rows = []
for meth in ("gmg", "gmg", "dd", "amg", "direct", "cg"):          # gmg twice: the first run includes compiling the Numba kernels
    if meth == "cg" and n > 40:
        continue
    t = time.perf_counter()
    try:
        res = VX.compress(occ, 1.0, axis=2, method=meth, tol=1e-8)
    except Exception as ex:
        print(f"{meth:34s} failed: {ex}")
        continue
    dt = time.perf_counter() - t
    label = res["method"] + (" (first run, compiles)" if meth == "gmg" and not rows else "")
    rows.append(meth)
    print(f"{label[:34]:34s} {dt:7.1f}s {res['iterations']:11d} {res['residual']:10.1e} {res['E_app']:12.4f}")
