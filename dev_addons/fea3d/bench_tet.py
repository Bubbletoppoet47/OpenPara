"""Run this on YOUR machine with YOUR STL:   python bench_tet.py my.stl [--tris 20000,60000,150000] [--graded] [--linear] [--plate 0.02] [--solve]

For each surface triangle count it prints: time to reduce, the deviation from the original (both ways), the tetrahedra gmsh makes (time, count, worst quality),
the unknowns, the memory used so far, and with --solve a sliding compression test along Z (bottom plate fixed in Z, top plate pushed 1 %) with the
apparent modulus and the solve time.  Start small; the numbers tell you how far you can go on your RAM before you try the full 638 000 triangles.
NOT YET RUN by its author."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))); import boot  # noqa: E402  (shared/, core/ and the add-on folders)
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

import fem3d as F
import repair as R
import tet as TT

ap = argparse.ArgumentParser()
ap.add_argument("stl")
ap.add_argument("--tris", default="20000,60000,150000")
ap.add_argument("--graded", action="store_true")
ap.add_argument("--biggest", type=float, default=4.0)
ap.add_argument("--growth", type=float, default=0.5)
ap.add_argument("--linear", action="store_true")
ap.add_argument("--solve", action="store_true")
ap.add_argument("--plate", type=float, default=0.02, help="plate thickness as a fraction of the length (default 0.02)")
ap.add_argument("--axis", type=int, default=2)
ap.add_argument("--E", type=float, default=10000.0)
ap.add_argument("--nu", type=float, default=0.3)
args = ap.parse_args()


def memory():
    try:
        import psutil
        return f"{psutil.Process().memory_info().rss / 1e9:.2f} GB"
    except Exception:
        try:
            import resource
            return f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6:.2f} GB (peak)"
        except Exception:
            return "n/a (pip install psutil)"


def progress(stage, frac=None):
    print(f"      {stage}" + ("" if frac is None else f" {frac * 100:.0f} %"), flush=True)


t = time.time()
mesh = R.to_mesh(*R.arrays(R.load(args.stl)))
op, nm = TT.surface_problems(mesh)
print(f"{args.stl}: {mesh.n_cells:,} triangles, {op} open edges, {nm} non-manifold edges  (read in {time.time() - t:.1f} s, memory {memory()})")
if op or nm:
    print("The surface is not closed: repair it in a Mesh tab first.")
    sys.exit(2)
ref = TT.Reference(mesh)
for n in [int(x) for x in args.tris.split(",")]:
    print(f"\n=== {n:,} triangles, {'graded' if args.graded else 'uniform'}, {'linear' if args.linear else 'quadratic'} ===")
    t = time.time()
    surf, info = TT.reduce_surface(mesh, n)
    print(f"  reduce: {info['triangles_out']:,} triangles in {time.time() - t:.1f} s, open edges {info.get('open_edges')}, retries {info['retries']}")
    t = time.time()
    dv = ref.deviation(surf)
    print(f"  deviation: largest {dv['max']:.4g}, 99.9 % under {dv['p999']:.4g}, mean {dv['mean']:.4g}, volume {dv['volume_change'] * 100:+.3f} %  ({time.time() - t:.1f} s)")
    t = time.time()
    try:
        nodes, conn, ti = TT.tetrahedralise(surf, "graded" if args.graded else "uniform", args.biggest, args.growth, 1 if args.linear else 2, progress)
    except Exception as ex:
        print(f"  gmsh FAILED: {ex}")
        continue
    print(f"  tetrahedra: {ti['tets']:,} ({ti['algorithm']}, {time.time() - t:.1f} s), nodes {ti['nodes']:,}, unknowns {3 * ti['nodes']:,}, quality worst {ti['q_min']:.3f} / "
          f"1 % {ti['q_p1']:.3f}, slivers {ti['slivers']:,}  memory {memory()}")
    if not args.solve:
        continue
    try:
        t = time.time()
        m = TT.TetModel(nodes, conn).assemble(args.E, args.nu, progress)
        print(f"  matrix: {m.K.nnz:,} non-zeros ({m.K.nnz * 12 / 1e9:.2f} GB) in {time.time() - t:.1f} s, memory {memory()}")
        lo, hi = nodes.min(0), nodes.max(0)
        g = F.plate_groups(lo, hi, args.axis, 0.01, False, args.plate * (hi[args.axis] - lo[args.axis]))
        t = time.time()
        sol = F.solve(m, g, "auto", tol=1e-6, progress=progress)
        app = F.apparent(m, g, sol, args.axis)
        print(f"  solved: {sol['method']}, {sol['iterations']} iterations, residual {sol['residual']:.1e}, {time.time() - t:.1f} s -> E_apparent {app['E_app']:.1f} "
              f"({app['E_app'] / args.E:.4f} of E), memory {memory()}")
    except MemoryError:
        print("  ran out of memory in the matrix / solver: use fewer triangles, graded tetrahedra or linear tetrahedra")
        break
