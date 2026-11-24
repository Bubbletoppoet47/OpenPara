"""3D FEA, hex-dominant meshing (mesh type "Hex-dominant" of the advanced mesh options): a block of hexahedra inside the part, tetrahedra next to the surface,
pyramids joining them; the surface mesh is patch by patch, as always.

  elements    shape functions, patch tests (a linear displacement field gives the constant strain), rigid motions and volumes of the 8- and 20-node
              hexahedra and the 5- and 13-node pyramids; a block of 8-node bricks does not lock in bending
  conformity  every inner face is shared by exactly two elements, the faces of one element are exactly the surface triangles, no hanging nodes, the
              element volumes add up to the part, no element is inverted - for several parts, linear and quadratic
  patches     the borders of a split face are mesh edges and the patches' triangles stay inside their patches; local sizes still work
  accuracy    tension bar (exact), cantilever against tetrahedra and beam theory, gravity, pressure, force balance - linear and quadratic
  fallback    a thin part (no room for bricks) and a part with an inner cavity are meshed with tetrahedra and the note says why
  window      the Mesh type drop-down, the counts per type, the quality report, the results, save / open, the Study output
"""
import os, sys, tempfile, shutil, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "parametric"), os.path.join(HERE, "shared")]
import numpy as np
import build123d as b
import solid_elem as el, solid_fem as fem, solid_geom as sg, solid_model as sm, solid_mesh as smesh, solid_hexmesh as hm

E_, NU = 200000.0, 0.3
D = fem.material_matrix(E_, NU)

# ================================================================================================================ the elements
for order in (1, 2):
    nodes = np.vstack([el.CORNERS, el.MIDS])[:8 if order == 1 else 20]
    N, dN = el.shape(order, nodes)
    assert np.allclose(N, np.eye(len(nodes)), atol=1e-12), "a shape function is 1 at its node and 0 at the others"
    p = np.random.RandomState(1).uniform(-1, 1, (7, 3))
    N, dN = el.shape(order, p)
    assert np.allclose(N.sum(1), 1) and np.allclose(dN.sum(1), 0) and np.allclose(N @ nodes, p, atol=1e-12), "partition of unity, linear field exact"
    for ax in range(3):
        q = p.copy(); q[:, ax] += 1e-6
        assert np.allclose((el.shape(order, q)[0] - N) / 1e-6, dN[:, :, ax], atol=1e-4), "the derivatives are the derivatives"

rs = np.random.RandomState(3)
EPS = lambda A: np.array([A[0, 0], A[1, 1], A[2, 2], A[0, 1] + A[1, 0], A[1, 2] + A[2, 1], A[0, 2] + A[2, 0]])
for kind, order in (("hex", 1), ("hex", 2)):                       # a distorted brick: a linear displacement field = constant strain and stress
    base = np.vstack([el.CORNERS, el.MIDS])[:8 if order == 1 else 20]
    c = el.CORNERS * np.array([10.0, 6.0, 4.0]) + rs.uniform(-0.8, 0.8, (8, 3))
    X = np.zeros_like(base); X[:8] = c
    if order == 2:
        for k, (a, bb) in enumerate(el.HEX_EDGES):
            X[8 + k] = 0.5 * (c[a] + c[bb])
    X = X[None]
    K = el.stiffness(kind, X, D)[0]
    A = rs.uniform(-1e-3, 1e-3, (3, 3))
    ue = (X[0] @ A.T).reshape(1, -1)
    assert abs((K @ ue[0]).reshape(-1, 3).sum(0)).max() < 1e-6 * abs(K @ ue[0]).max(), "the nodal forces are in balance"
    _v, mean, vol = el.recover(kind, X, D, ue)
    assert np.allclose(mean[0], D @ EPS(A), rtol=1e-8, atol=1e-8 * abs(D @ EPS(A)).max()), (kind, order, "patch test")
    assert abs(vol[0] - el.volumes(kind, X)[0]) < 1e-9 * vol[0]
    assert abs(K @ np.tile([1.0, -2.0, 0.5], X.shape[1])).max() < 1e-6 * abs(K).max(), "a translation costs no energy"
    assert abs(K @ np.cross([0.01, 0.02, -0.03], X[0]).ravel()).max() < 1e-6 * abs(K).max(), "a small rotation costs no energy"
P5 = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 6.0]])
for order in (1, 2):                                                # a pyramid is the collapsed brick
    pc = P5 if order == 1 else np.vstack([P5] + [0.5 * (P5[a] + P5[bb])[None] for a, bb in el.PYR_EDGES])
    hx = el.as_hex("pyr", np.arange(len(pc))[None])[0]
    X = pc[hx][None]
    A = rs.uniform(-1e-3, 1e-3, (3, 3))
    _v, mean, vol = el.recover("pyr", X, D, (pc @ A.T)[hx].reshape(1, -1))
    assert abs(vol[0] - 200.0) < 1e-9 and np.allclose(mean[0], D @ EPS(A), rtol=1e-7, atol=1e-7 * abs(D @ EPS(A)).max()), ("pyramid", order)
    K = el.stiffness("pyr", X, D)[0]
    assert abs(K @ np.tile([1.0, 2.0, -3.0], X.shape[1])).max() < 1e-6 * abs(K).max()
pyr = np.array([[0, 3, 2, 1, 4]])                                    # a pyramid with the base the wrong way round is turned the right way
assert el.orient_pyramids(P5, pyr)[0].tolist() == [0, 1, 2, 3, 4] and el.orient_pyramids(P5, np.array([[0, 1, 2, 3, 4]]))[0].tolist() == [0, 1, 2, 3, 4]
inv = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1.0]]); inv[4:, 2] = -1.0
try:
    el.stiffness("hex", inv[None], D); raise SystemExit("an inverted brick must be refused")
except el.ElementError:
    pass
print("elements ok")

# a block of 8-node bricks in bending (a cantilever 2 bricks deep): no locking
def brick_beam(nx, ny, nz, L, hh, order=1):
    xs, ys, zs = np.linspace(0, L, nx + 1), np.linspace(0, hh, ny + 1), np.linspace(0, hh, nz + 1)
    nid = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k
    nodes = np.array([(x, y, z) for x in xs for y in ys for z in zs])
    conn = np.array([[nid(i, j, k), nid(i + 1, j, k), nid(i + 1, j + 1, k), nid(i, j + 1, k), nid(i, j, k + 1), nid(i + 1, j, k + 1), nid(i + 1, j + 1, k + 1),
                      nid(i, j + 1, k + 1)] for i in range(nx) for j in range(ny) for k in range(nz)])
    return nodes, conn
nodes, conn = brick_beam(10, 2, 2, 20.0, 2.0)
q = {"nodes": nodes, "conn": conn, "groups": [{"kind": "hex", "conn": conn}], "order": 1}
root = np.where(nodes[:, 0] < 1e-9)[0]; tip = np.where(nodes[:, 0] > 20.0 - 1e-9)[0]
force = np.zeros(3 * len(nodes)); force[3 * tip + 2] = -1.0 / len(tip)
u, _r, _i, _K, _D = fem.solve(q, E_, NU, [(root, None)], force)
I = 2.0 * 2.0 ** 3 / 12.0; G = E_ / (2 * (1 + NU)); kap = 10 * (1 + NU) / (12 + 11 * NU)
timo = 1.0 * 20.0 ** 3 / (3 * E_ * I) + 1.0 * 20.0 / (kap * G * 4.0)
tipw = abs(u[tip, 2].mean())
assert abs(tipw - timo) / timo < 0.06, ("8-node bricks lock in bending", tipw, timo)
print("brick beam ok", tipw, timo)

# ================================================================================================================ meshes of several parts
def surface_area(g):
    return sum(f["area"] for f in g["faces"])

def check_mesh(g, q, label, expect_hex=True):
    """The conformity of a mesh from sm.get_mesh, checked here independently of the mesher's own checks."""
    nodes, groups = q["nodes"], q["groups"]
    corner = {"tet": 4, "hex": 8, "pyr": 5}
    keys = []
    for gr in groups:
        c = gr["conn"][:, :corner[gr["kind"]]]
        if gr["kind"] == "tet":
            fs = ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2))
        elif gr["kind"] == "hex":
            fs = ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        else:
            fs = ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 1, 2, 3))
        for f in fs:
            r = c[:, list(f)]
            if r.shape[1] == 3:
                r = np.concatenate([np.full((len(r), 1), -1), r], axis=1)
            keys.append(np.sort(r, axis=1))
    keys = np.vstack(keys)
    u, cnt = np.unique(keys, axis=0, return_counts=True)
    assert cnt.max() <= 2, (label, "a face shared by more than two elements")
    bnd = u[cnt == 1]
    surf = np.sort(np.concatenate([np.concatenate([np.full((len(t), 1), -1), t[:, :3]], axis=1) for t in q["faces"].values()]), axis=1)
    surf = np.unique(surf, axis=0)
    assert bnd.shape == surf.shape and np.array_equal(bnd, surf), (label, "the faces with one element are exactly the surface triangles", bnd.shape, surf.shape)
    # no node is left over, no node is shared that is not an element corner / mid-edge node
    used = np.unique(np.concatenate([gr["conn"].ravel() for gr in groups]))
    assert len(used) == len(nodes), (label, "unused nodes", len(used), len(nodes))
    ql = q["quality"]
    assert ql["inverted"] == 0 and ql["elements"] == sum(len(gr["conn"]) for gr in groups)
    if expect_hex:
        assert ql["hexes"] > 0 and ql["pyramids"] > 0 and ql["hex_share"] > 0 and 0 < ql["hex_volume_share"] < 1, (label, ql["hexes"])
    return ql

hexdom = lambda order, **kw: dict(smesh.default_mesh(), advanced=True, order=order, type="hexdom", **kw)

def mesh_of(g, h, order, **kw):
    s = sm.default_setup(); s["h"] = h; s["mesh"] = hexdom(order, **kw)
    return sm.get_mesh(g, h, {}, lambda: False, lambda t: None, smesh.resolve(g, s, h))

shapes = {}
shapes["box"] = b.Solid.make_box(100, 40, 40)
shapes["plate-hole"] = b.Solid.make_box(100, 60, 40) - b.Solid.make_cylinder(12, 50, b.Plane.XY.offset(-5).move(b.Location((50, 30, 0))))
shapes["boss"] = b.Solid.make_box(80, 60, 40) + b.Solid.make_cylinder(16, 40, b.Plane.XY.offset(40).move(b.Location((40, 30, 0))))
shapes["L-bracket"] = b.Solid.make_box(80, 40, 20) + b.Solid.make_box(20, 40, 60)
shapes["sphere"] = b.Solid.make_sphere(30)
for name, solid in shapes.items():
    g = sg.analyze(solid)
    for order in (1, 2):
        q = mesh_of(g, 4.0, order)
        assert q.get("hexdom_note") is None and q["order"] == order, (name, q.get("hexdom_note"))
        ql = check_mesh(g, q, f"{name} order {order}")
        # the volume of the elements is the volume the surface triangles enclose (the CAD volume differs a little where a surface is curved)
        assert abs(ql["volume"] - g["volume"]) < 0.02 * g["volume"], (name, ql["volume"], g["volume"])
        if order == 2:
            assert q["groups"][0]["conn"].shape[1] == 10 and any(gr["kind"] == "hex" and gr["conn"].shape[1] == 20 for gr in q["groups"])
            assert any(gr["kind"] == "pyr" and gr["conn"].shape[1] == 13 for gr in q["groups"])
        else:
            assert q["groups"][0]["conn"].shape[1] == 4 and any(gr["kind"] == "hex" and gr["conn"].shape[1] == 8 for gr in q["groups"])
        assert 0.0 < ql["ratio_min"] <= 1.0 and ql["hex_jacobian_min"] > 0.99
    print(f"mesh {name}: {ql['elements']} elements, hexahedra {ql['hexes']} ({ql['hex_share']*100:.0f} %, {ql['hex_volume_share']*100:.0f} % of the volume), "
          f"tets {ql['tets']}, pyramids {ql['pyramids']}, worst radius ratio {ql['ratio_min']:.3f}")
# a finer mesh puts more of the volume into bricks
gb = sg.analyze(shapes["box"])
qc, qf = mesh_of(gb, 5.0, 1), mesh_of(gb, 2.5, 1)
assert qf["quality"]["hex_volume_share"] > qc["quality"]["hex_volume_share"] > 0.3, (qc["quality"]["hex_volume_share"], qf["quality"]["hex_volume_share"])
# the same part and size give the same mesh
assert np.array_equal(mesh_of(gb, 5.0, 1)["hexes"], qc["hexes"])
# the mesh type is part of the cache key: tetrahedra and hex-dominant never answer for one another
s1 = sm.default_setup(); s1["h"] = 5.0; s1["mesh"] = dict(smesh.default_mesh(), advanced=True, order=1, type="tets")
s2 = sm.default_setup(); s2["h"] = 5.0; s2["mesh"] = hexdom(1)
k1, k2 = sm.mesh_key(gb, 5.0, smesh.resolve(gb, s1, 5.0)), sm.mesh_key(gb, 5.0, smesh.resolve(gb, s2, 5.0))
assert k1 != k2 and sm.mesh_key(gb, 5.0, None) == sm.mesh_key(gb, 5.0, smesh.resolve(gb, sm.default_setup(), 5.0)), "the plain mesh keeps its key"
cache = {}
sm.get_mesh(gb, 5.0, cache, lambda: False, lambda t: None, smesh.resolve(gb, s1, 5.0)); sm.get_mesh(gb, 5.0, cache, lambda: False, lambda t: None, smesh.resolve(gb, s2, 5.0))
assert len(cache) == 2 and sum(1 for v in cache.values() if len(v.get("hexes", ()))) == 1
print("conformity ok")

# ================================================================================================================ patches
sp = sg.analyze(shapes["box"])
top = next(f["id"] for f in sp["faces"] if f["normal"][2] > 0.99)
gp = sg.analyze(shapes["box"], [{"face": sg.face_sig(sp, top), "cols": 4, "rows": 2, "u": None}])
patches = [f for f in gp["faces"] if f["cell"] is not None]
assert len(patches) == 8
q = mesh_of(gp, 5.0, 2)
ql = check_mesh(gp, q, "box with split top face")
assert ql["hexes"] > 0
for f in patches:
    i, j = f["cell"]
    tr = q["faces"][f["id"]][:, :3]
    pts = q["nodes"][np.unique(tr)]
    lo = np.array([i * 25.0, j * 20.0]); hi = lo + [25.0, 20.0]
    assert (pts[:, 2] > 40 - 1e-6).all() and (pts[:, :2] >= lo - 1e-6).all() and (pts[:, :2] <= hi + 1e-6).all(), ("a triangle sticks out of its patch", f["cell"])
    area = 0.5 * np.linalg.norm(np.cross(q["nodes"][tr[:, 1]] - q["nodes"][tr[:, 0]], q["nodes"][tr[:, 2]] - q["nodes"][tr[:, 0]]), axis=1).sum()
    assert abs(area - 500.0) < 1e-6, ("the triangles of a patch cover exactly the patch", f["cell"], area)
by_cell = {f["cell"]: f["id"] for f in patches}
for (i, j), fid in by_cell.items():                                 # neighbouring patches share their border nodes, and those lie on the border
    if i < 3:
        shared = np.intersect1d(np.unique(q["faces"][fid][:, :3]), np.unique(q["faces"][by_cell[(i + 1, j)]][:, :3]))
        assert len(shared) >= 3 and np.allclose(q["nodes"][shared, 0], 25.0 * (i + 1)), ("the border of two patches is made of shared mesh nodes", (i, j))
# a support / load on one patch: the force goes exactly where it was put, the part stays in balance
setup = sm.default_setup(); setup["h"] = 5.0; setup["splits"] = [{"face": sg.face_sig(sp, top), "cols": 4, "rows": 2, "u": None, "col_sizes": [None] * 4, "row_sizes": [None] * 2}]
setup["mesh"] = hexdom(1)
xm = next(f["id"] for f in gp["faces"] if f["normal"][0] < -0.99)
setup["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(gp, xm)]}]
setup["loads"] = [{"kind": "force", "faces": [sg.face_sig(gp, patches[3]["id"])], "f": [0.0, 0.0, -400.0]}]
res = sm.run(gp, sm.resolve(gp, setup), {})
assert res["counts"]["hexes"] > 0 and res["equilibrium"] < 1e-9 and abs(res["reaction"][2] - 400.0) < 1e-6, (res["counts"], res["equilibrium"], res["reaction"])
print("patches ok")
# local sizes still work: more triangles on the refined face, mesh still conforming
face_x = next(f["id"] for f in sg.analyze(shapes["box"])["faces"] if f["normal"][0] > 0.99)
coarse = mesh_of(gb, 5.0, 1)
ls = sm.default_setup(); ls["h"] = 5.0; ls["mesh"] = hexdom(1, face_sizes=[{"face": sg.face_sig(gb, face_x), "h": 1.5}])
fine = sm.get_mesh(gb, 5.0, {}, lambda: False, lambda t: None, smesh.resolve(gb, ls, 5.0))
assert len(fine["faces"][face_x]) > 3 * len(coarse["faces"][face_x]), (len(fine["faces"][face_x]), len(coarse["faces"][face_x]))
check_mesh(gb, fine, "local size", expect_hex=fine["quality"]["hexes"] > 0)
ls["mesh"] = hexdom(1, face_sizes=[{"face": sg.face_sig(gb, face_x), "h": 3.0}])               # a mild refinement keeps the block of hexahedra (a strong one, 1/4 of the size or less, may not)
mild = sm.get_mesh(gb, 5.0, {}, lambda: False, lambda t: None, smesh.resolve(gb, ls, 5.0))
assert len(mild["faces"][face_x]) > 1.5 * len(coarse["faces"][face_x]) and mild["quality"]["hexes"] > 0, (mild["quality"]["hexes"], mild.get("hexdom_note"))
check_mesh(gb, mild, "mild local size", expect_hex=True)
print("local sizes ok", mild["quality"]["hexes"], "hexahedra with a mild one,", fine["quality"]["hexes"], "with 1.5 on a 5.0 mesh")

# ================================================================================================================ fallbacks
thin = sg.analyze(b.Solid.make_box(100, 60, 6))
qt = mesh_of(thin, 4.0, 2)
assert qt["quality"]["hexes"] == 0 and qt["quality"]["pyramids"] == 0 and qt.get("hexdom_note") and "thin" in qt["hexdom_note"].lower() and len(qt["groups"]) == 1
assert qt["quality"]["inverted"] == 0 and qt["viewcells"] is None
cav = b.Solid.make_box(60, 60, 60) - b.Solid.make_box(20, 20, 20).moved(b.Location((20, 20, 20)))
try:
    gc = sg.analyze(cav)
except Exception as ex:
    gc = None
if gc is not None:
    qcv = mesh_of(gc, 5.0, 1)
    assert qcv["quality"]["hexes"] == 0 and "cavity" in (qcv.get("hexdom_note") or ""), qcv.get("hexdom_note")
    print("cavity falls back:", qcv["hexdom_note"][:60])
big = sg.analyze(b.Solid.make_box(30, 30, 30))
assert mesh_of(big, 20.0, 1).get("hexdom_note"), "the element size is larger than the part's room for bricks"
# the tetrahedra-only meshes have not changed: same keys, same arrays, no hexahedra
plain = sm.get_mesh(gb, 5.0, {}, lambda: False, lambda t: None, None)
assert "hexes" not in plain and plain["viewcells"] is None and len(plain["groups"]) == 1 and plain["conn"] is plain["groups"][0]["conn"]
print("fallbacks ok:", qt["hexdom_note"][:70])

# ================================================================================================================ accuracy
def bar_setup(g, solid_dims, h, order, typ, load, kind="force", xaxis=0):
    s = sm.default_setup(); s["h"] = h
    s["mesh"] = dict(smesh.default_mesh(), advanced=True, order=order, type=typ)
    nrm = lambda v: next(f["id"] for f in g["faces"] if np.dot(f["normal"], v) > 0.99)
    s["supports"] = [{"mode": "fixed", "faces": [sg.face_sig(g, nrm([-1, 0, 0]))]}]
    s["loads"] = [{"kind": "force", "faces": [sg.face_sig(g, nrm([1, 0, 0]))], "f": list(load)}] if kind == "force" else \
                 [{"kind": "pressure", "faces": [sg.face_sig(g, nrm([1, 0, 0]))], "p": load}] if kind == "pressure" else [{"kind": "gravity", "g": 9.81, "dir": [0, 0, -1]}]
    return s

Lx, Wy, Hz = 96.0, 36.0, 36.0
gcant = sg.analyze(b.Solid.make_box(Lx, Wy, Hz))
Icant = Wy * Hz ** 3 / 12.0
shear = 1000.0 * Lx / ((10 * (1 + NU) / (12 + 11 * NU)) * (E_ / (2 * (1 + NU))) * Wy * Hz)
beam = 1000.0 * Lx ** 3 / (3 * E_ * Icant) + shear                  # Timoshenko beam: bending and shear
tips, vms, ens = {}, {}, {}
for order in (2, 1):
    for typ in ("tets", "hexdom"):
        r = sm.run(gcant, sm.resolve(gcant, bar_setup(gcant, (Lx, Wy, Hz), 6.0 if order == 2 else 3.0, order, typ, [0.0, 0.0, -1000.0])), {})
        tips[(order, typ)] = abs(r["u"][:, 2].min()); vms[(order, typ)] = r["vm_max"]; ens[(order, typ)] = r["energy"]
        assert r["equilibrium"] < 1e-9 and abs(r["reaction"][2] - 1000.0) < 1e-6, r["reaction"]
        assert (r["counts"]["hexes"] > 0) == (typ == "hexdom"), (order, typ, r["counts"])
        assert abs(r["volume"] - Lx * Wy * Hz) < 1e-6 * Lx * Wy * Hz and abs(r["mass"] - Lx * Wy * Hz * 7850e-9) < 1e-6
        assert r["n_elements"] == sum(r["counts"].values()) and np.isfinite(r["vm_node"]).all() and r["vm_node"].min() >= 0
        print(f"cantilever {typ:6s} order {order}: tip {tips[(order, typ)]:.5f} (beam + shear {beam:.5f}) vm max {r['vm_max']:.1f} elements {r['n_elements']} {r['counts']}")
assert abs(tips[(2, "hexdom")] - tips[(2, "tets")]) / tips[(2, "tets")] < 0.03, tips
assert abs(tips[(2, "hexdom")] - beam) / beam < 0.10, (tips, beam)
assert abs(tips[(1, "hexdom")] - tips[(2, "tets")]) / tips[(2, "tets")] < 0.06, ("linear hex-dominant is close to the quadratic tetrahedra", tips)
assert tips[(1, "hexdom")] > tips[(1, "tets")], ("linear hex-dominant is stiffer than linear tetrahedra? it must be the softer one", tips)
assert abs(ens[(2, "hexdom")] - ens[(2, "tets")]) / ens[(2, "tets")] < 0.03, ens
assert 0.6 * 1000 * Lx * 18 / Icant < vms[(2, "hexdom")] < 1.5 * 1000 * Lx * 18 / Icant, vms                     # a stress about the beam value (clamped corner peak)

# tension: exact displacement, uniform stress
gt = sg.analyze(b.Solid.make_box(60, 30, 30))
for order in (2, 1):
    r = sm.run(gt, sm.resolve(gt, bar_setup(gt, None, 5.0 if order == 2 else 3.0, order, "hexdom", [1000.0, 0.0, 0.0])), {})
    assert r["counts"]["hexes"] > 0
    assert abs(r["umax"] - 1000.0 * 60 / (900.0 * E_)) / (1000.0 * 60 / (900.0 * E_)) < 0.025, (order, r["umax"])
    assert abs(np.median(r["vm_el"]) - 1000.0 / 900.0) < 0.03 * 1000.0 / 900.0 + 0.02, (order, np.median(r["vm_el"]))
    assert r["equilibrium"] < 1e-9 and abs(r["reaction"][0] + 1000.0) < 1e-6
# pressure and gravity on a hex-dominant mesh
r = sm.run(gt, sm.resolve(gt, bar_setup(gt, None, 5.0, 1, "hexdom", 10.0, kind="pressure")), {})
assert abs(r["reaction"][0] - 10.0 * 900.0) < 1e-6 and abs(np.median(r["vm_el"]) - 10.0) < 0.5 and r["u"][:, 0].min() < 0
r = sm.run(gt, sm.resolve(gt, bar_setup(gt, None, 5.0, 2, "hexdom", None, kind="gravity")), {})
assert abs(r["reaction"][2] - 60 * 900.0 * 7850e-9 * 9.81) < 1e-6 * 60 * 900.0 * 7850e-9 * 9.81 * 1e3 and r["equilibrium"] < 1e-9, (r["reaction"], r["applied"])
print("accuracy ok")

# a rigid-body check on the whole hex-dominant matrix: a translation and a rotation of every node cost no energy
q2 = mesh_of(gt, 6.0, 2)
Kmat, _D2 = fem.assemble(q2["nodes"], q2["groups"], E_, NU)
for mode in range(6):
    v = fem.rigid_modes(q2["nodes"])[:, mode]
    assert abs(Kmat @ v).max() < 1e-7 * abs(Kmat.diagonal()).max() * max(np.abs(v).max(), 1), ("rigid mode", mode, abs(Kmat @ v).max())
# the same matrix for a mesh of one kind of element, many sizes: assembled twice is the same
K2, _ = fem.assemble(q2["nodes"], q2["groups"], E_, NU)
assert abs(K2 - Kmat).max() == 0
print("stiffness matrix ok")

# ================================================================================================================ the viewer's picture
try:
    import pyvista  # noqa
    import solid_view as sv
    r = sm.run(gt, sm.resolve(gt, bar_setup(gt, None, 5.0, 1, "hexdom", [1000.0, 0.0, 0.0])), {})
    assert r["viewcells"] is not None
    surf, orig = sv._result_surface(r["nodes"], r["viewcells"])
    assert abs(surf.area - surface_area(gt)) < 1e-6 * surface_area(gt), (surf.area, surface_area(gt))
    assert len(orig) == surf.n_points and surf.n_cells == sum(len(t) for t in sm.get_mesh(gt, 5.0, {}, lambda: False, lambda t: None,
                                                                                         smesh.resolve(gt, dict(sm.default_setup(), mesh=hexdom(1), h=5.0), 5.0))["faces"].values())
    print("view surface ok", surf.n_cells)
except ImportError:
    print("pyvista not installed: view check skipped")

# ================================================================================================================ the window
from PyQt6.QtWidgets import QApplication, QMessageBox
app = QApplication.instance() or QApplication([])
MSGS = []
QMessageBox.information = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.warning = staticmethod(lambda *a, **k: MSGS.append(a[2] if len(a) > 2 else ""))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
import pm_model as pmod, sk_tools as sk
import solid_tab, solid_study
T = tempfile.mkdtemp(prefix="opara_hd_")
d_ = pmod.Document(); d_.params = {"T": "40"}
s_ = d_.add(pmod.new_feature("sketch", plane={"base": "Top"})); d_.rebuild(); m_ = d_.models[s_["id"]]
rr = sk.add_rect_corner(m_, (0, 0), (100, 40))
m_.add_con("dim_h", [("ln", rr["lns"][0])], value=100.0); m_.add_con("dim_v", [("ln", rr["lns"][1])], value=40.0)
sk.solve_model(m_); d_.store_sketch(s_["id"])
d_.add(pmod.new_feature("extrude", sketch=s_["id"], depth="T")); d_.rebuild()
part_file = os.path.join(T, "block.gpd"); open(part_file, "w").write(d_.to_json())
w = solid_tab.SolidWindow(threaded=False)
w.resize(1300, 1700); w.show()
assert w.create_project(os.path.join(T, "block_hd")) and w.import_file(part_file), MSGS
w.cb_adv.setChecked(True); app.processEvents()
mesh_sec = next(x for x in w.sections if x.title == "Mesh")
assert [w.type_combo.itemData(i) for i in range(w.type_combo.count())] == ["tets", "hexdom"] and w.type_combo.currentData() == "tets"
assert mesh_sec.isAncestorOf(w.type_combo) and w.adv_box.isAncestorOf(w.type_combo) and "Hex-dominant" in w.type_combo.itemText(1)
def face(nv):
    return next(f["id"] for f in w.geom["faces"] if np.dot(f["normal"], nv) > 0.99)
w.select_faces([face([-1, 0, 0])]); assert w.add_support("fixed")
w.select_faces([face([1, 0, 0])]); assert w.add_load("force", {"f": [0.0, 0.0, -1000.0]})
w.set_size("5"); w.inputs_changed()
w.order_combo.setCurrentIndex(w.order_combo.findData(1)); w.order_combo.activated.emit(w.order_combo.currentIndex())
assert w.run_mesh() and "tetrahedra" in w.mesh_lbl.text() and "hexahedra" not in w.mesh_lbl.text()
w.type_combo.setCurrentIndex(w.type_combo.findData("hexdom")); w.type_combo.activated.emit(w.type_combo.currentIndex())
assert w.setup["mesh"]["type"] == "hexdom" and w.mesh_q is None, "a changed mesh type: the old mesh no longer applies"
assert w.run_mesh() and w.mesh_q["quality"]["hexes"] > 0
cn = w.mesh_q["quality"]
assert "hexahedra" in w.mesh_lbl.text() and f"{cn['hexes']:,} hexahedra" in w.mesh_lbl.text() and f"{cn['elements']:,} elements" in w.mesh_lbl.text(), w.mesh_lbl.text()
ql_text = w.quality_lbl.text()
w.outline.select("Mesh"); app.processEvents()
assert w.quality_box.isVisibleTo(w) and f"Hexahedra {cn['hexes']:,}" in ql_text and "% of the volume" in ql_text and "pyramids" in ql_text and "radius ratio" in ql_text, ql_text
assert w.run_solve() and w.result["counts"]["hexes"] == cn["hexes"] and "Hexahedra" in w.res_lbl.text() and "Pyramids" in w.res_lbl.text(), w.res_lbl.text()
assert w.result["viewcells"] is not None and w.result["n_elements"] == cn["elements"]
# the Study tab outputs
src = open(os.path.join(HERE, "dev_addons", "solid_fea", "solid_study.py")).read()
assert '("sf.tets", "Elements", True)' in src and 'r.get("n_elements", r["n_tets"])' in src
# a size too big for any brick: tetrahedra and the note
w.set_size("30"); w.inputs_changed()
assert w.run_mesh() and w.mesh_q["quality"]["hexes"] == 0 and w.mesh_q.get("hexdom_note")
assert "Tetrahedra only" in w.quality_lbl.text() and "hexahedra" not in w.mesh_lbl.text(), (w.quality_lbl.text(), w.mesh_lbl.text())
assert w.run_solve() and "Hex-dominant was asked for" in w.res_lbl.text() and w.result["hexdom_note"]
# back to a size with room, save, open
w.set_size("5"); w.inputs_changed()
w.type_combo.setCurrentIndex(w.type_combo.findData("hexdom")); w.type_combo.activated.emit(w.type_combo.currentIndex())
assert w.run_solve() and w.result["counts"]["hexes"] > 0
assert w.save(), w.status_lbl.text()
folder = w.path
w2 = solid_tab.SolidWindow.open_project(None, folder, threaded=False)
assert w2.setup["mesh"]["type"] == "hexdom" and w2.type_combo.currentData() == "hexdom" and w2.setup["mesh"]["order"] == 1 and not w2.is_dirty()
w2.import_state(w2.export_state())
assert w2.setup["mesh"]["type"] == "hexdom" and w2.type_combo.currentData() == "hexdom"
# a project from before the mesh type existed opens with tetrahedra
import sim_project as spj
st = json.load(open(spj.state_path(folder)))
st["setup"]["mesh"].pop("type")
json.dump(st, open(spj.state_path(folder), "w"))
w3 = solid_tab.SolidWindow.open_project(None, folder, threaded=False)
assert w3.setup["mesh"]["type"] == "tets" and w3.type_combo.currentData() == "tets"
shutil.rmtree(T, ignore_errors=True)
print("OK solid hex-dominant")
os._exit(0)
