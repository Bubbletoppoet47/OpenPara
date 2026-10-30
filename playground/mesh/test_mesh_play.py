"""Tests of the mesh playground.  Run:  python test_mesh_play.py   (from this folder or the repository root; about 2-4 minutes)."""
import os
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPARA_USER_DIR", tempfile.mkdtemp())

import remesh as M
import repair as R
import section as S
import shapes
import solid as SO

bad = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        bad.append(what)


C = shapes.corpus()
print("repair")
for name, m in C.items():
    fixed, rep = R.repair(m)
    a = rep["after"]
    check(a["ok"], f"{name}: ends as one closed, oriented shell ({R.describe(a)})")
    if a["volume"] and rep["before"]["closed"] and rep["before"]["flipped_triangles"] == 0 and not rep["notes"]:
        check(abs(a["volume"] - rep["before"]["volume"]) < 1e-9 * a["volume"], f"{name}: a clean mesh is left untouched")
ref = R.repair(C["blob"])[0]
v0 = R.diagnose(ref)["volume"]
for k in ("blob_flipped", "blob_spikes", "blob_fin", "blob_degenerate", "blob_floaters"):
    v = R.diagnose(R.repair(C[k])[0])["volume"]
    check(v is not None and abs(v - v0) / v0 < 0.002, f"{k}: volume back to the clean blob's (within 0.2 %)")
for k in ("blob_holes", "blob_all"):
    v = R.diagnose(R.repair(C[k])[0])["volume"]
    check(v is not None and abs(v - v0) / v0 < 0.02, f"{k}: volume within 2 % of the clean blob (filled holes are flat)")
bar_fixed, _ = R.repair(C["bar"])
check(abs(R.diagnose(bar_fixed)["volume"] - 10000) < 1e-6, "bar: sharp corners are not mistaken for spikes")

print("remesh")
m = ref
P, _T = R.arrays(m)
top, bot = P[np.argmax(P[:, 2])], P[np.argmin(P[:, 2])]
zone = [{"kind": "sphere", "center": tuple(top), "radius": 8, "size": 0.8}]
n0_top, n0_bot = M.local_counts(m, top, 8), M.local_counts(m, bot, 8)
r = M.refine(m, 10.0, zone)
check(M.local_counts(r, top, 8) > 4 * n0_top and M.local_counts(r, bot, 8) == n0_bot, "refine in a sphere: many more facets there, none elsewhere")
check(R.diagnose(r)["closed"] and M.deviation(m, r, 800)[0] < 1e-9, "refine: stays closed and the shape does not change at all")
r = M.refine(m, 1.2)
check(len(r.faces) // 4 > 2.5 * (len(m.faces) // 4), "refine globally: facet count grows")
r = M.coarsen(m, 4.0)
d = R.diagnose(r)
check(d["closed"] and len(r.faces) // 4 < 0.3 * (len(m.faces) // 4), f"coarsen globally: far fewer facets, still closed ({len(r.faces) // 4})")
check(M.deviation(m, r, 800)[1] < 0.012 * d["size"], "coarsen: 95 % of the surface within 1.2 % of the size")
r = M.remesh(m, 3.0, zone)
check(R.diagnose(r)["closed"] and M.local_counts(r, top, 8) > 3 * n0_top and M.local_counts(r, bot, 8) < n0_bot, "remesh: finer in the zone, coarser elsewhere")
r = M.reduce(m, 0.7)
check(len(r.faces) // 4 < 0.4 * (len(m.faces) // 4) and M.deviation(m, r, 800)[1] < 0.012 * d["size"], "reduce 70 % (quadric decimation)")
sub = M.subdivide(m, 1)
check(len(sub.faces) // 4 == 4 * (len(m.faces) // 4), "subdivide: four times the triangles")
box = [{"kind": "box", "lo": (-100, -100, 10), "hi": (100, 100, 100), "size": 1.0}]
r = M.refine(m, 10.0, box)
check(M.local_counts(r, top, 8) > 3 * n0_top, "refine in a box")
cv = M.refine(C["bone"], 6.0, [{"kind": "curvature", "size": 1.5, "angle": 0.3}])
check(R.diagnose(cv)["closed"] and len(cv.faces) // 4 >= len(C["bone"].faces) // 4, "curvature zone runs")

print("solids")
bar, _ = R.repair(C["bar"])
s = SO.faceted_solid(bar)
check(s.is_valid and abs(s.volume - 10000) < 1e-6 and len(s.faces()) == 768, "faceted solid of the bar: valid, exact volume, one face per triangle")
bl = ref
s = SO.faceted_solid(bl)
check(s.is_valid and abs(s.volume - SO.mesh_volume(bl)) < 1e-6 * s.volume, "faceted solid of the blob")
g = SO.tet_mesh(bl)
q = SO.tet_quality(g)
check(q["inverted"] == 0 and abs(q["volume"] - SO.mesh_volume(bl)) < 1e-6 * q["volume"], f"tetrahedra of the blob: none inverted, volume exact ({q['cells']} cells)")
g = SO.tet_mesh(R.repair(C["scan"])[0])
check(g.n_cells > 1000 and SO.tet_quality(g)["inverted"] == 0, "tetrahedra of the noisy scan (smoothed copy when it cuts itself)")
try:
    SO.faceted_solid(C["torus"], max_tris=1000)
    check(False, "too large a mesh is refused")
except ValueError:
    check(True, "too large a mesh is refused for the faceted solid")

print("section -> FEA   (cantilever bar against beam theory)")
bar = shapes.box_bar(100, 10, 10)
sec = S.cut(bar, (0, 0, 5), (0, 0, 1))
check(abs(sec.area - 1000) < 1e-6, "mid-plane cut of the bar is 100 x 10")
x0, x1, h, t, E, F = 0.0, 100.0, 10.0, 10.0, 200000.0, 1000.0
res = S.fea(sec, {"E": E, "nu": 0.3, "t": t, "mode": "stress", "order": 2}, [{"mode": "fixed", "where": lambda x, y: x < 1e-6}],
            [{"kind": "traction", "tx": 0.0, "ty": -F / (h * t), "where": lambda x, y: x > x1 - 1e-6}], h=1.0)
nd = res["_mesh_in"]["nodes"]
tip = res["u"][:len(nd)][nd[:, 0] > x1 - 1e-6, 1].mean()
beam = -4 * F * (x1 - x0) ** 3 / (E * t * h ** 3)
print(f"       tip deflection {tip:.5f} mm, beam theory {beam:.5f} mm")
check(abs(tip / beam - 1) < 0.03, "tip deflection within 3 % of beam theory")
check(abs(res["equilibrium"]["reactions"]["fy"] - F) < 1e-3 * F and abs(res["equilibrium"]["sum_fy"]) < 1e-3 * F, "support reaction equals the load (balance is zero)")
sec = S.cut(bar, (50, 5, 5), (1, 0, 0))
check(abs(sec.area - 100) < 1e-6, "cut across the bar (normal X) is its 10 x 10 section")
sec2 = S.cut(R.repair(shapes.torus())[0], (0, 0, 0), (0, 0, 1))
check(len(sec2.poly.interiors) == 1 and abs(sec2.area - 3400) < 150, f"the torus cut through its middle is a ring: one hole, area {sec2.area:.0f}")

print("section -> CFD")
sec = S.cut(ref, (0, 0, 0), (0, 0, 1))
t0 = time.time()
rc, mesh, info = S.cfd(sec, speed=0.2, steps=50, h_body=1.6, h_far=8.0)
print(f"       {len(mesh['tris'])} triangles, Re {rc['re']:.0f}, {time.time() - t0:.0f} s")
check(rc["mass"]["relative"] < 1e-6 or abs(rc["mass"]["net"]) < 1e-6 * rc["mass"]["inflow"], "mass in equals mass out")
check(rc["forces"]["along"] > 0, "the force on the body points downstream")
check(np.isfinite(rc["u"]).all() and np.isfinite(rc["p"]).all(), "velocity and pressure are finite")

print("\n" + ("ALL OK" if not bad else f"{len(bad)} FAILED:\n  " + "\n  ".join(bad)))
sys.exit(1 if bad else 0)
