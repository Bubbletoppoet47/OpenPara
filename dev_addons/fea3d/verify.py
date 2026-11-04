"""Built-in checks for the voxel and tetrahedral solvers.  Each returns rows {name, got, expect, tol, ok, note}; ok is None for information only."""
import numpy as np

import lattice as LT
import voxel as VX
from tasks import sub, tick

E0, NU0 = 10000.0, 0.3


def row(name, got, expect=None, tol=None, note="", fmt="{:.4g}"):
    ok = None
    if expect is not None and tol is not None:
        ok = bool(abs(got - expect) <= tol * abs(expect))
    return {"name": name, "got": got, "expect": expect, "tol": tol, "ok": ok, "note": note, "fmt": fmt}


def cantilever_voxel(t, E=1000.0, nu=0.3):
    n = 6 * t
    occ = np.ones((n, t, t), bool)
    fixed = {(0, j, k, c): 0.0 for j in range(t + 1) for k in range(t + 1) for c in range(3)}
    P = 1.0
    loads = {(n, j, k, 2): -P / (t + 1) ** 2 for j in range(t + 1) for k in range(t + 1)}
    m, u = VX.solve_bc(occ, 1.0, fixed, loads, E, nu, tol=1e-10)
    tip = -u.reshape(-1, 3)[m.layer_nodes(0, 1)][:, 2].mean()
    I, G, A = t ** 4 / 12, E / (2 * (1 + nu)), t * t
    theory = P * n ** 3 / (3 * E * I) + P * n / ((5 / 6) * G * A)
    return tip, theory


def voxel_checks(progress=None):
    out = []
    tick(progress, "Solid cube", 0.0)
    r = VX.compress(LT.cube(10), 1.0, 2, 0.01, E0, NU0)
    out.append(row("Solid cube, compression: E_apparent / E", r["E_app"] / E0, 1.0, 1e-4, "uniform strain, must equal the material"))
    f = r["model"].matvec(r["u"])
    imbalance = abs(f[3 * r["model"].layer_nodes(2, 0) + 2].sum() + f[3 * r["model"].layer_nodes(2, 1) + 2].sum()) / r["F"]
    out.append(row("Solid cube: force on the bottom face equals force on the top face (difference / force)", imbalance, 0.0, None, "should be ~0", "{:.2e}"))
    out[-1]["ok"] = bool(imbalance < 1e-5)
    rb = VX.compress(LT.cube(10), 1.0, 2, 0.01, E0, NU0, bonded=True)
    out.append(row("Solid cube, bonded faces: E_apparent / E", rb["E_app"] / E0, None, None, "above 1 on purpose: bonded faces stop the sideways expansion"))
    tick(progress, "Bundle of bars", 0.15)
    occ = LT.columns(3, 9, 5, 24)
    r = VX.compress(occ, 1.0, 2, 0.01, E0, NU0)
    out.append(row("Bundle of square bars: E_apparent / (E x volume fraction)", r["E_app"] / (E0 * (5 / 9) ** 2), 1.0, 1e-3, "exact answer: bars carry the load alone"))
    for t_, tol in ((4, 0.04), (8, 0.03)):
        tick(progress, f"Cantilever {t_} voxels thick", 0.3 if t_ == 4 else 0.4)
        tip, theory = cantilever_voxel(t_)
        out.append(row(f"Cantilever, {t_} voxels thick, 6 long: tip deflection / beam theory", tip / theory, 1.0, tol, "Timoshenko beam theory (bending + shear)"))
    tick(progress, "Voxel size convergence", 0.5)
    ratios = []
    sizes = [1.0, 0.6, 0.4]
    R, side, Lz = 3.0, 10.0, 12.0
    for k, h in enumerate(sizes):
        tick(progress, f"Convergence: voxel size {h:g}", 0.5 + 0.4 * k / len(sizes))
        n = int(round(side / h)), int(round(side / h)), int(round(Lz / h))
        g = [(np.arange(c) + 0.5) * h for c in n]
        X, Y = np.meshgrid(g[0], g[1], indexing="ij")
        disc = ((X - side / 2) ** 2 + (Y - side / 2) ** 2) <= R ** 2
        occ = np.repeat(disc[:, :, None], n[2], axis=2)
        r = VX.compress(occ, h, 2, 0.01, E0, NU0)
        exact = np.pi * R ** 2 / side ** 2
        ratios.append(r["E_app"] / (E0 * exact))
    out.append(row(f"Round bar, voxel size {sizes[0]:g} -> {sizes[-1]:g} mm: error of E_apparent", abs(ratios[-1] - 1), None, None,
                   "errors at each size: " + ", ".join(f"{abs(x - 1) * 100:.1f} %" for x in ratios) + " (the stair-stepped edge shrinks with the voxel)", "{:.3f}"))
    out[-1]["ok"] = bool(abs(ratios[-1] - 1) < 0.03 and abs(ratios[-1] - 1) <= abs(ratios[0] - 1) + 1e-9)
    out += group_checks()
    out += adaptive_checks()
    tick(progress, "Done", 1.0)
    return out


def group_checks(progress=None):
    """The node-group path against the quick preset and against exact answers."""
    import fem3d as F
    out = []
    tick(progress, "Groups on a solid cube", 0.0)
    occ = LT.cube(10)
    m = VX.Model(occ, 1.0, E0, NU0, np.zeros(3))
    lo, hi = np.zeros(3), np.array([10.0] * 3)
    g = F.plate_groups(lo, hi, 2, 0.01, False, None, 1.0)
    res = F.solve(m, g)
    ap = F.apparent(m, g, res, 2)
    out.append(row("Groups: solid cube, E_apparent / E", ap["E_app"] / E0, 1.0, 1e-4, "same answer as the quick compression preset"))
    ref = VX.compress(occ, 1.0, 2, 0.01, E0, NU0)
    out.append(row("Groups vs the older compression path: ratio", ap["E_app"] / ref["E_app"], 1.0, 1e-6))
    tick(progress, "Force group", 0.5)
    g2 = [F.Group("bottom", "fixed", [False, False, True], ops=[("add", F.Region.box([-1, -1, -0.01], [11, 11, 0.01]))]),
          F.Group("pin", "fixed", [True, True, False], ops=[("add", F.Region.box([-1, -1, -0.01], [0.01, 0.01, 0.01]))]),
          F.Group("top", "force", [False, False, True], [0, 0, -1000.0], ops=[("add", F.Region.box([-1, -1, 9.99], [11, 11, 11]))])]
    r2 = F.solve(m, g2)
    d = -r2["u"].reshape(-1, 3)[m.layer_nodes(2, 1)][:, 2].mean()
    out.append(row("Force group on a cube: shortening / (F L / E A)", d / (1000.0 * 10 / (E0 * 100)), 1.0, 0.06, "force shared equally per node, but corner and edge nodes carry less area, so a few % off is expected"))
    tick(progress, "Done", 1.0)
    return out


def adaptive_checks(progress=None):
    """Adaptive bricks against uniform voxels and against exact answers."""
    import octree as OT
    import fem3d as F
    out = []
    tick(progress, "Adaptive cube", 0.0)
    occ = np.ones((16, 16, 16), bool)
    m = OT.AdaptiveModel(occ, 1.0, np.zeros(3), 2, 1.0).assemble(E0, NU0)
    g = F.plate_groups(np.zeros(3), np.full(3, 16.0), 2, 0.01, False, None, 1.0)
    ap = F.apparent(m, g, F.solve(m, g), 2, area=256.0)
    out.append(row("Adaptive bricks, solid cube: E_apparent / E", ap["E_app"] / E0, 1.0, 1e-6, f"{m.summary()}; uniform stress must be reproduced across the tied nodes"))
    tick(progress, "Adaptive cantilever", 0.3)
    E, nu, t = 1000.0, 0.3, 12
    n = 6 * t
    occ = np.ones((n, t, t), bool)
    tips = {}
    for name, mod in (("uniform", VX.Model(occ, 1.0, E, nu, np.zeros(3))), ("adaptive", OT.AdaptiveModel(occ, 1.0, np.zeros(3), 2, 1.0).assemble(E, nu))):
        big = 1e9
        fix = F.Group("fix", "fixed", [1, 1, 1], ops=[("add", F.Region.box([-1, -1, -1], [0.01, big, big]))])
        ld = F.Group("load", "force", [0, 0, 1], [0, 0, -1.0], ops=[("add", F.Region.box([n - 0.01, -1, -1], [big, big, big]))])
        r = F.solve(mod, [fix, ld])
        tips[name] = (-r["u"].reshape(-1, 3)[ld.mask(mod.node_xyz())][:, 2].mean(), mod.ne)
    I, G = t ** 4 / 12, E / (2 * (1 + nu))
    theory = n ** 3 / (3 * E * I) + n / ((5 / 6) * G * t * t)
    out.append(row("Adaptive bricks, cantilever tip deflection / uniform voxels", tips["adaptive"][0] / tips["uniform"][0], 1.0, 0.01, f"{tips['adaptive'][1]:,} bricks instead of {tips['uniform'][1]:,}"))
    out.append(row("Adaptive bricks, cantilever tip deflection / beam theory", tips["adaptive"][0] / theory, 1.0, 0.04))
    tick(progress, "Adaptive round bar", 0.6)
    n = 40
    X, Y = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5, indexing="ij")
    occ = np.repeat((((X - n / 2) ** 2 + (Y - n / 2) ** 2) <= 16.0 ** 2)[:, :, None], 40, axis=2)
    res = {}
    for name, mod in (("uniform", VX.Model(occ, 1.0, E0, NU0, np.zeros(3))), ("adaptive", OT.AdaptiveModel(occ, 1.0, np.zeros(3), 3, 1.0).assemble(E0, NU0))):
        g = F.plate_groups(np.zeros(3), np.array([n, n, 40.0]), 2, 0.01, False, None, 1.0)
        r = F.solve(mod, g)
        res[name] = (F.apparent(mod, g, r, 2, area=float(n * n))["E_app"], mod.ne)
    out.append(row("Adaptive bricks, round bar: E_apparent / uniform voxels", res["adaptive"][0] / res["uniform"][0], 1.0, 0.005, f"{res['adaptive'][1]:,} bricks instead of {res['uniform'][1]:,}"))
    tick(progress, "Done", 1.0)
    return out


def _tet_compress(model, lo, hi, area, strain=0.01, method="direct"):
    import fem3d as F
    g = F.plate_groups(lo, hi, 2, strain, False, 1e-6 * (hi[2] - lo[2]))
    sol = F.solve(model, g, method, tol=1e-10)
    ap = F.apparent(model, g, sol, 2, area=area)
    return ap, sol


def tet_checks(progress=None):
    """The tetrahedral solver against exact answers.  The tolerances are first guesses (the checks were written before they could be run)."""
    import pyvista as pv
    import fem3d as F
    import repair as R
    import tet as TT
    out = []

    def guard(name, fn):
        try:
            fn()
        except Exception as ex:
            out.append(row(name, float("nan"), None, None, f"stopped with {type(ex).__name__}: {ex}"))
            out[-1]["ok"] = False

    tick(progress, "Patch tests (no gmsh)", 0.0)
    for order in (1, 2):
        def patch(order=order):
            nodes, tets = TT.box_tets((3, 3, 3), (10.0, 10.0, 10.0))
            if order == 2:
                nodes, tets = TT.to_quadratic(nodes, tets)
            m = TT.TetModel(nodes, tets).assemble(E0, NU0)
            B = VX.rigid_modes(m)
            leak = float(np.abs(m.K @ B).max() / (np.abs(m.K).max() * np.abs(B).max()))
            out.append(row(f"{'Quadratic' if order == 2 else 'Linear'} tetrahedra: stiffness times a rigid motion (should be 0)", leak, 0.0, None, "relative to the matrix size", "{:.2e}"))
            out[-1]["ok"] = bool(leak < 1e-10)
            ap, sol = _tet_compress(m, np.zeros(3), np.full(3, 10.0), 100.0)
            out.append(row(f"{'Quadratic' if order == 2 else 'Linear'} tetrahedra, block: E_apparent / E", ap["E_app"] / E0, 1.0, 1e-6, "uniform strain: any tetrahedra must reproduce it exactly"))
            f = m.fields(sol["u"])
            err = float(np.abs(f["szz"] + E0 * 0.01).max() / (E0 * 0.01))
            out.append(row(f"{'Quadratic' if order == 2 else 'Linear'} tetrahedra, block: stress in every element equals E x strain (largest error)", err, 0.0, None, "", "{:.2e}"))
            out[-1]["ok"] = bool(err < 1e-6)
            eq = sol["equilibrium"]
            tot = max(abs(eq["reaction"][a] + eq["applied"][a]) for a in range(3)) / max(abs(ap["F"]), 1e-30)
            out.append(row(f"{'Quadratic' if order == 2 else 'Linear'} tetrahedra, block: force balance (error / reaction)", tot, 0.0, None, "", "{:.2e}"))
            out[-1]["ok"] = bool(tot < 1e-6)
        guard(f"patch test order {order}", patch)
    tick(progress, "Cantilever", 0.2)
    E, nu, t, L = 1000.0, 0.3, 2.0, 12.0
    I, G = t ** 4 / 12, E / (2 * (1 + nu))
    k_th = 1.0 / (L ** 3 / (3 * E * I) + L / ((5 / 6) * G * t * t))
    for order, div, tol in ((2, (24, 4, 4), 0.08), (1, (24, 4, 4), None)):
        def cant(order=order, div=div, tol=tol):
            nodes, tets = TT.box_tets(div, (L, t, t))
            if order == 2:
                nodes, tets = TT.to_quadratic(nodes, tets)
            m = TT.TetModel(nodes, tets).assemble(E, nu)
            big = 1e9
            delta = 0.01
            fix = F.Group("fix", "fixed", [1, 1, 1], ops=[("add", F.Region.box([-1, -1, -1], [1e-6, big, big]))])
            ld = F.Group("load", "disp", [0, 0, 1], [0, 0, -delta], ops=[("add", F.Region.box([L - 1e-6, -1, -1], [big, big, big]))])
            sol = F.solve(m, [fix, ld], "direct", tol=1e-10)
            k = abs(sol["reactions"]["fix"][2]) / delta
            out.append(row(f"Cantilever, {'quadratic' if order == 2 else 'linear'} tetrahedra ({m.ne:,}): tip stiffness / beam theory", k / k_th, 1.0, tol,
                           "Timoshenko beam theory; linear tetrahedra are known to be too stiff in bending (information only)" if tol is None else "Timoshenko beam theory (bending + shear)"))
        guard(f"cantilever order {order}", cant)
    tick(progress, "Block cut and surface reduction", 0.4)

    def crop():
        cube = pv.Box(bounds=(0, 10, 0, 10, 0, 10), level=0, quads=False).triangulate().subdivide(3, subfilter="linear").clean()
        blk = TT.crop_block(R.to_mesh(*R.arrays(cube)), (0.5, 1.0, 0.6))
        vol = abs(R.signed_volume(*R.arrays(blk)))
        out.append(row("Block cut from the middle of a 10 mm cube (50 % x 100 % x 60 %): volume", vol, 300.0, 1e-3, f"{TT.surface_problems(blk)} open / non-manifold edges after capping"))
    guard("block cut", crop)

    def reduce():
        sph = pv.Sphere(radius=10.0, theta_resolution=120, phi_resolution=120).triangulate().clean()
        sph = R.to_mesh(*R.arrays(sph))
        red, info = TT.reduce_surface(sph, 3000)
        dv = TT.Reference(sph).deviation(red)
        out.append(row("Sphere r = 10 reduced from %s to %s triangles: largest deviation / radius" % (f"{sph.n_cells:,}", f"{info['triangles_out']:,}"), dv["max"] / 10.0, None, None,
                       f"volume change {dv['volume_change'] * 100:+.3f} %, {info.get('open_edges', 0)} open edges (information; a sphere's chord error bounds it)", "{:.4f}"))
        out[-1]["ok"] = bool(info.get("open_edges", 1) == 0 and info.get("nonmanifold_edges", 1) == 0 and abs(dv["volume_change"]) < 0.05)
    guard("reduce surface", reduce)
    tick(progress, "gmsh: round bar", 0.6)
    for mode in ("uniform", "graded"):
        def bar(mode=mode):
            cyl = pv.Cylinder(radius=3.0, height=12.0, direction=(0, 0, 1), center=(0, 0, 0), resolution=40, capping=True).triangulate().clean().subdivide(2, subfilter="linear")
            cyl = R.to_mesh(*R.arrays(cyl))
            nodes, conn, info = TT.tetrahedralise(cyl, mode, 4.0, 0.5, 2)
            m = TT.TetModel(nodes, conn).assemble(E0, NU0)
            lo, hi = nodes.min(0), nodes.max(0)
            area = float(m.vol.sum() / (hi[2] - lo[2]))
            ap, _sol = _tet_compress(m, lo, hi, area)
            out.append(row(f"Round bar through gmsh ({mode}, {m.ne:,} quadratic tetrahedra): E_apparent / E", ap["E_app"] / E0, 1.0, 1e-5,
                           f"{info['algorithm']}, worst element quality {info['q_min']:.3f}, {info['slivers']} slivers"))
        guard(f"round bar {mode}", bar)
    tick(progress, "Done", 1.0)
    return out


def format_rows(rows):
    lines = []
    for r in rows:
        mark = {True: "PASS", False: "FAIL", None: "info"}[r["ok"]]
        exp = "" if r["expect"] is None else "   expected " + r["fmt"].format(r["expect"])
        tol = "" if r["tol"] is None else f" (+/- {r['tol'] * 100:g} %)"
        lines.append(f"[{mark}] {r['name']}: {r['fmt'].format(r['got'])}{exp}{tol}" + (f"\n        {r['note']}" if r["note"] else ""))
    return "\n".join(lines)
