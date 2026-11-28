"""PA-3 on the paths of a real slice (plan chapter 10; the "pending" lines of test_print_fabric.py).

A cube is sliced by the real engine (orca_core, the compiled module: set ORCA_CORE_BUILD_DIR), its printed paths go into print_fabric, and the
stiffness of a brick mesh of the same cube comes out.  What is checked is what the synthetic paths of test_print_fabric.py cannot say:
  * the z convention: the first road fills 0 to 0.2 mm and the last ends at the top of the cube (the path points are the TOPS of the roads);
  * the plastic is conserved: the fabric holds the volume the paths hold, and the mean plastic fraction of the mesh is the volume of the part's roads over
    the volume of the cube;
  * the walls are denser than the middle, the in-plane stiffness is the same along x and y (the walls and the crossed infill balance), and between layers
    the part is the weaker way (E3 < E1) with the road constants given.
Without the compiled engine it says so and passes."""
import faulthandler; faulthandler.dump_traceback_later(250, exit=True)
import os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "engines", "orca_core", "python"))
sys.path.insert(0, os.path.join(HERE, "dev_addons", "solid_fea"))
import orca_core as oc
from orca_core import errors, _engine

try:
    _engine._core()
except errors.EngineMissing:
    print("print fabric on real paths: skipped (the compiled engine is not built here; set ORCA_CORE_BUILD_DIR to test it)")
    sys.exit(0)
import solid_fem as fem
import print_fabric as pf

ORIGIN = np.array([100.0, 100.0, 0.0])
S = 20.0
v = np.array([(x, y, z) for z in (0, S) for y in (0, S) for x in (0, S)], float) + ORIGIN
f = np.array([t for a, b, c, d in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)) for t in ((a, b, c), (a, c, d))])
settings = {"layer_change_gcode": "G92 E0", "wall_loops": "2", "sparse_infill_density": "25%", "sparse_infill_pattern": "grid", "skirt_loops": "0",
            "brim_type": "no_brim", "top_shell_layers": "3", "bottom_shell_layers": "3"}
job = oc.Job(settings, threads=2)
job.add_object(v, f, "cube")
res = job.slice()
paths = res.paths

# ---- the paths and the z convention
part = paths.select(np.isin(paths.role, pf.PART_ROLES))
assert abs(paths.layer_z[0] - 0.2) < 1e-4 and abs(paths.layer_z[-1] - S) < 1e-3
first = part.layer_slice(0)
assert abs(first.points[:, 2].max() - 0.2) < 1e-4 and abs(first.height.max() - 0.2) < 1e-4, "the first road is 0.2 mm high and its points are at its top"
fab = pf.Fabric.from_paths(paths, cell_xy=0.5)
lo, hi = fab.bbox()
assert lo[2] > -1e-6 and lo[2] < 0.25 and abs(hi[2] - S) < 0.25, (lo, hi)          # the roads fill 0 .. 20: top of the road minus its height is the bottom
assert abs(fab.total_volume() - part.volumes().sum()) < 1e-3 * part.volumes().sum(), (fab.total_volume(), part.volumes().sum())
print("fabric: %.0f mm3 of plastic in %d cells, z from %.2f to %.2f" % (fab.total_volume(), len(fab.ids), lo[2], hi[2]))

# ---- a brick mesh of the cube: 1 mm elements
n = 20
g = (np.arange(n) + 0.5)
cen = np.stack(np.meshgrid(g, g, g, indexing="ij"), axis=-1).reshape(-1, 3) + ORIGIN
vol = np.ones(len(cen))
C = {"E1": 2400.0, "E2": 2000.0, "E3": 1500.0, "G12": 800.0, "G23": 600.0, "G13": 600.0, "nu12": 0.33, "nu23": 0.35, "nu13": 0.30}
out = pf.element_stiffness(fab, cen, vol, C, sigma=1.0, sigma_z=0.6)
phi = out["phi"].reshape(n, n, n)
want = part.volumes().sum() / S ** 3
assert abs(phi.mean() - want) < 0.06 * want, "mean plastic fraction %.3f, the cube's roads say %.3f" % (phi.mean(), want)
assert out["empty"] == 0, out["empty"]
edge = np.concatenate([phi[:2].ravel(), phi[-2:].ravel(), phi[:, :2].ravel(), phi[:, -2:].ravel()])
mid = phi[5:15, 5:15, 5:15].ravel()
assert edge.mean() > 1.5 * mid.mean(), "walls are denser than the middle (%.2f against %.2f)" % (edge.mean(), mid.mean())
D = fem.unpack_D(out["D21"]).reshape(n, n, n, 6, 6)
core = D[5:15, 5:15, 5:15].reshape(-1, 6, 6).mean(axis=0)
assert abs(core[0, 0] - core[1, 1]) < 0.10 * 0.5 * (core[0, 0] + core[1, 1]), "in the plane the infill is the same along x and y (%.0f, %.0f)" % (core[0, 0], core[1, 1])
assert core[2, 2] < core[0, 0], "between layers is the weaker way (%.0f against %.0f)" % (core[2, 2], core[0, 0])
print("mean phi %.3f (roads say %.3f); wall phi %.2f, middle phi %.2f; core stiffness xx %.0f yy %.0f zz %.0f MPa" % (phi.mean(), want, edge.mean(), mid.mean(),
                                                                                                             core[0, 0], core[1, 1], core[2, 2]))
print("print fabric on real paths: ok")
