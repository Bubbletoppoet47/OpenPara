"""Command line for the mesh playground.

    python mesh_play.py corpus                        build the test shapes, repair each, print a before / after table
    python mesh_play.py repair  in.stl out.stl        diagnose, repair, write
    python mesh_play.py remesh  in.stl out.stl SIZE [--sphere x y z r size] [--box x0 y0 z0 x1 y1 z1 size] [--curv size]
    python mesh_play.py reduce  in.stl out.stl FRACTION
    python mesh_play.py solid   in.stl out.step       faceted solid (STEP) and a tetrahedral mesh summary
    python mesh_play.py fea     in.stl                cut at mid-height, cantilever FEA (left face fixed, right face loaded), print the tip deflection
    python mesh_play.py cfd     in.stl                cut at mid-height, 2D flow past the outline

STL files are read and written with pyvista.  Run it from this folder (the modules import each other).
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import remesh as M
import repair as R
import section as S
import shapes
import solid as SO


def corpus_table(out=print):
    rows = []
    for name, m in shapes.corpus().items():
        t = time.time()
        fixed, rep = R.repair(m)
        a = rep["after"]
        rows.append((name, R.describe(rep["before"]), R.describe(a), a["ok"], time.time() - t))
        out(f"{name:16s} {'OK ' if a['ok'] else 'NOT'}  {rows[-1][1]}\n{'':20s}-> {rows[-1][2]}   [{rep['notes'] and '; '.join(rep['notes']) or 'nothing to do'}]")
    out(f"\n{sum(r[3] for r in rows)} of {len(rows)} end as one closed, consistently oriented shell")
    return rows


def midplane(mesh):
    b = mesh.bounds
    return ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "corpus":
        rows = corpus_table()
        return 0 if all(r[3] for r in rows) else 1
    m = R.load(argv[2])
    if cmd == "repair":
        fixed, rep = R.repair(m)
        print("before:", R.describe(rep["before"]))
        print("after: ", R.describe(rep["after"]))
        for n in rep["notes"]:
            print("  -", n)
        fixed.save(argv[3])
    elif cmd == "remesh":
        size, zones, i = float(argv[4]), [], 5
        while i < len(argv):
            if argv[i] == "--sphere":
                zones.append({"kind": "sphere", "center": tuple(map(float, argv[i + 1:i + 4])), "radius": float(argv[i + 4]), "size": float(argv[i + 5])})
                i += 6
            elif argv[i] == "--box":
                zones.append({"kind": "box", "lo": tuple(map(float, argv[i + 1:i + 4])), "hi": tuple(map(float, argv[i + 4:i + 7])), "size": float(argv[i + 7])})
                i += 8
            elif argv[i] == "--curv":
                zones.append({"kind": "curvature", "size": float(argv[i + 1])})
                i += 2
            else:
                raise SystemExit(f"unknown option {argv[i]}")
        r = M.remesh(m, size, zones)
        print(len(m.faces) // 4, "->", len(r.faces) // 4, "triangles; deviation max/p95/mean %.4g / %.4g / %.4g" % M.deviation(m, r))
        r.save(argv[3])
    elif cmd == "reduce":
        r = M.reduce(m, float(argv[4]))
        print(len(m.faces) // 4, "->", len(r.faces) // 4, "triangles; deviation max/p95/mean %.4g / %.4g / %.4g" % M.deviation(m, r))
        r.save(argv[3])
    elif cmd == "solid":
        s = SO.faceted_solid(m)
        print("solid volume %.4g (mesh %.4g), valid=%s, %d faces" % (s.volume, SO.mesh_volume(m), s.is_valid, len(s.faces())))
        from build123d import export_step
        export_step(s, argv[3])
        g = SO.tet_mesh(m)
        print("tetrahedra:", SO.tet_quality(g))
    elif cmd == "fea":
        sec = S.cut(m, midplane(m), (0, 0, 1))
        x0, x1, y0, y1 = sec.poly.bounds[0], sec.poly.bounds[2], sec.poly.bounds[1], sec.poly.bounds[3]
        t = float(m.bounds[5] - m.bounds[4])
        res = S.fea(sec, {"E": 200000.0, "nu": 0.3, "t": t, "mode": "stress", "order": 2}, [{"mode": "fixed", "where": lambda x, y: x < x0 + 1e-6 * (x1 - x0)}],
                    [{"kind": "traction", "tx": 0.0, "ty": -100.0, "where": lambda x, y: x > x1 - 1e-6 * (x1 - x0)}])
        print("max von Mises %.4g MPa, max displacement %.4g mm" % (res["vm"].max(), np.abs(res["u"]).max()))
    elif cmd == "cfd":
        sec = S.cut(m, midplane(m), (0, 0, 1))
        res, mesh, info = S.cfd(sec, steps=100)
        print("Re %.0f, force along %.4g N/m, across %.4g N/m, status %s" % (res["re"], res["forces"]["along"], res["forces"]["across"], res["status"]))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
