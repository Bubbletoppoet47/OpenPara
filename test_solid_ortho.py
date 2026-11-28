"""Printed-part analysis, the solver part (planning/design/slicer, chapter 10; items PA-1 and PA-2): a material matrix for each element, orthotropic materials.

Tests A1 to A4 and A7 of the plan (10.7) run here with no window, no mesher and no printer, on small structured meshes of tetrahedra and bricks.
A5 and A6 need the slicer's toolpaths (PA-3) and are listed as pending, not as passed.

What is checked, and against what:
  A1  an orthotropic material whose axes are not the global axes, pulled in tension: the stretch equals the closed form 1/E(n) = v.S.v, which is computed here from the
      compliance in the material's own axes and does not use the rotation code under test.  Tetrahedra and bricks.
  A2  all three moduli equal: exactly the isotropic matrix, and exactly the isotropic stiffness matrix of the whole mesh.
  A3  a cantilever of orthotropic material (stiff along the beam, soft in shear): against the beam theory with shear, within the tolerance the isotropic test uses.
  A4  a patch test with a different matrix in every layer of elements: a uniform stretch along the layers is reproduced exactly.
  A7  the 21 numbers of each of a million matrices fit in memory (84 MB), and the rotation and unpacking of a million take seconds.
And that an isotropic group gives the result it gave before (the same arithmetic, not only the same to a tolerance).
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "solid_fea"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "shared")]
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
import solid_fem as fem
import solid_elem as elem

fails = []
def ok(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


# ------------------------------------------------------------------------------------------------------------------------ meshes
_KUHN = [(0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7), (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7)]        # six tetrahedra around the diagonal 0-7 of a cube (corner bits x, y, z)


def grid(nx, ny, nz, L, w, t):
    xs, ys, zs = np.linspace(0, L, nx + 1), np.linspace(0, w, ny + 1), np.linspace(0, t, nz + 1)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    nodes = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    idx = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k
    return nodes, idx


def tet_mesh(nx, ny, nz, L, w, t):
    nodes, idx = grid(nx, ny, nz, L, w, t)
    tets = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                c = [idx(i + (b & 1), j + ((b >> 1) & 1), k + ((b >> 2) & 1)) for b in range(8)]
                for a, b, c_, d in _KUHN:
                    tets.append([c[a], c[b], c[c_], c[d]])
    tets = np.array(tets)
    vol = fem._signed_vol(nodes[tets])
    tets[vol < 0] = tets[vol < 0][:, [0, 2, 1, 3]]
    return {"nodes": nodes, "tets": tets, "faces": {}}


def hex_conn(nx, ny, nz, L, w, t):
    nodes, idx = grid(nx, ny, nz, L, w, t)
    conn = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                conn.append([idx(i, j, k), idx(i + 1, j, k), idx(i + 1, j + 1, k), idx(i, j + 1, k),
                             idx(i, j, k + 1), idx(i + 1, j, k + 1), idx(i + 1, j + 1, k + 1), idx(i, j + 1, k + 1)])
    return nodes, np.array(conn)


def face_forces(nodes, conn_tets, plane_x, traction):
    """Consistent nodal forces (3 nn,) of a uniform traction (3,) on the triangles of the tetrahedra that lie in the plane x = plane_x."""
    f = np.zeros(3 * len(nodes))
    for tri in {tuple(sorted(t)) for tet in conn_tets for t in ((tet[1], tet[2], tet[3]), (tet[0], tet[2], tet[3]), (tet[0], tet[1], tet[3]), (tet[0], tet[1], tet[2]))
                if np.allclose(nodes[list(t), 0], plane_x)}:
        p = nodes[list(tri)]
        area = 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0]))
        for n in tri:
            f[3 * n:3 * n + 3] += traction * area / 3.0
    return f


def face_forces_hex(nodes, conn, plane_x, traction):
    """The same for bricks: a quadrilateral face of the brick carries a quarter of its force on each corner (what its shape functions give for a uniform traction)."""
    f = np.zeros(3 * len(nodes))
    for c in conn:
        for quad in ((0, 3, 7, 4), (1, 2, 6, 5)):
            q = [c[i] for i in quad]
            if np.allclose(nodes[q, 0], plane_x):
                p = nodes[q]
                area = 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])) + 0.5 * np.linalg.norm(np.cross(p[2] - p[0], p[3] - p[0]))
                for n in q:
                    f[3 * n:3 * n + 3] += traction * area / 4.0
    return f


def solve_dirichlet(K, f, fixed_dofs, values=None):
    """K u = f with some dofs fixed (to values, default zero)."""
    n = K.shape[0]
    fixed = np.zeros(n, bool)
    fixed[fixed_dofs] = True
    ub = np.zeros(n)
    if values is not None:
        ub[fixed_dofs] = values
    free = ~fixed
    K = K.tocsr()
    rhs = f[free] - K[free][:, fixed] @ ub[fixed]
    u = ub.copy()
    u[free] = spl.spsolve(K[free][:, free].tocsc(), rhs)
    return u


def node_at(nodes, p):
    return int(np.argmin(np.linalg.norm(nodes - np.asarray(p, float), axis=1)))


def rigid_pins(nodes, L, w, t):
    """Six constraints that stop every rigid motion and nothing else: [(node, direction)] -> dof list."""
    p0, p1, p2 = node_at(nodes, (0, 0, 0)), node_at(nodes, (0, w, 0)), node_at(nodes, (0, 0, t))
    return [3 * p0, 3 * p0 + 1, 3 * p0 + 2, 3 * p1 + 2, 3 * p1, 3 * p2]


# material used by the rotated tension tests: three clearly different moduli, all three Poisson ratios, a general rotation
E1, E2, E3, G12, G23, G13, N12, N23, N13 = 20000.0, 5000.0, 2500.0, 1800.0, 900.0, 1200.0, 0.30, 0.35, 0.25
Dl = fem.orthotropic_matrix(E1, E2, E3, G12, G23, G13, N12, N23, N13)
ang = np.radians
def rot(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    th = np.radians(deg)
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)
R = rot([1, 2, 3], 37.0)                                       # the material axes 1, 2, 3 are the columns of R, in the global frame


def closed_form_E(n, R):
    """Young's modulus along the unit vector n (global) of the material whose axes are the columns of R: 1 / (v . S_local . v) with v the local direction cosines.
    It uses only the compliance in the material's own axes."""
    S = np.linalg.inv(Dl)
    m = R.T @ np.asarray(n, float)                              # the direction in the material's axes
    v = np.array([m[0] ** 2, m[1] ** 2, m[2] ** 2, m[0] * m[1], m[1] * m[2], m[0] * m[2]])
    return 1.0 / float(v @ S @ v)


# ------------------------------------------------------------------------------------------------------------------------ the matrix itself
ok(np.allclose(Dl, Dl.T, rtol=1e-12, atol=1e-9), "the orthotropic matrix is symmetric")
ok(np.linalg.eigvalsh(Dl).min() > 0, "and positive definite")
S = np.linalg.inv(Dl)
ok(abs(S[0, 0] - 1 / E1) < 1e-15 and abs(S[0, 1] + N12 / E1) < 1e-15 and abs(S[1, 2] + N23 / E2) < 1e-15 and abs(S[3, 3] - 1 / G12) < 1e-15
   and abs(S[4, 4] - 1 / G23) < 1e-15 and abs(S[5, 5] - 1 / G13) < 1e-15, "its compliance has the constants it was made from")
for bad in ((0, 1, 1, 1, 1, 1, .3, .3, .3), (1, 1, 1, 1, 1, 1, .9, .3, .3), (1, 1, 1, 1, 1, -1, .3, .3, .3)):
    try:
        fem.orthotropic_matrix(*bad)
        ok(False, f"constants {bad} are refused")
    except fem.FemError as ex:
        ok(len(str(ex)) > 20, f"constants {bad} are refused, in words")
Kr = fem.stress_rotation(R)
ok(np.allclose(Kr @ np.linalg.inv(Kr), np.eye(6)) and abs(np.linalg.det(Kr) - 1) < 1e-9, "the stress rotation is a proper rotation of the six numbers")
Dg = fem.rotate_D(Dl, R)
ok(np.allclose(Dg, Dg.T, atol=1e-8) and abs(np.trace(fem.rotate_D(Dl, np.eye(3))) - np.trace(Dl)) < 1e-9, "the rotated matrix stays symmetric; the identity rotation changes nothing")
# the rotation of an isotropic matrix is itself
Diso = fem.material_matrix(3000.0, 0.3)
ok(np.allclose(fem.rotate_D(Diso, R), Diso, atol=1e-9), "an isotropic matrix does not change when rotated")
# per element rotations are the same as one at a time
Rs = np.stack([rot([1, 2, 3], a) for a in (10, 37, 80)])
ok(all(np.allclose(fem.rotate_D(Dl, Rs)[i], fem.rotate_D(Dl, Rs[i])) for i in range(3)), "a rotation for each element gives what one at a time gives")
P = fem.pack_D(fem.rotate_D(Dl, Rs))
ok(P.shape == (3, 21) and P.dtype == np.float32 and np.allclose(fem.unpack_D(P), fem.rotate_D(Dl, Rs), rtol=2e-6, atol=2e-3), "21 float32 numbers per element hold the matrix")
a = np.random.RandomState(0).randn(5, 6)
ok(np.array_equal(elem.apply_D(a, Diso), a @ Diso.T), "one matrix for all elements is exactly 'strain @ D.T' as before")

# ------------------------------------------------------------------------------------------------------------------------ A1 tension of a turned material
L_, w_, t_ = 20.0, 10.0, 10.0
m = tet_mesh(4, 2, 2, L_, w_, t_)
nodes = m["nodes"]
pins = rigid_pins(nodes, L_, w_, t_)
sigma = 10.0
# the load is the same traction pulling on both end faces, so that the six pins carry nothing and the stress is uniform
f = face_forces(nodes, m["tets"], L_, np.array([sigma, 0, 0])) + face_forces(nodes, m["tets"], 0.0, np.array([-sigma, 0, 0]))
ok(abs(f[0::3].sum()) < 1e-9 and abs(f[0::3][f[0::3] > 0].sum() - sigma * w_ * t_) < 1e-9, "A1: the nodal forces are a balanced pull of 10 MPa on the two end faces")
errs = []
for name, Rm in (("37 degrees about (1,2,3)", R), ("axes turned about z", rot([0, 0, 1], 30.0)), ("material 1 along x (no turn)", np.eye(3))):
    D_ = fem.rotate_D(Dl, Rm)
    K, _d0 = fem.assemble(nodes, [{"kind": "tet", "conn": m["tets"], "D": D_}], 1.0, 0.3)
    u = solve_dirichlet(K, f, pins)
    a_, b_ = node_at(nodes, (0, 0, 0)), node_at(nodes, (L_, 0, 0))
    stretch = (u[3 * b_] - u[3 * a_]) / L_
    expect = sigma / (closed_form_E([1, 0, 0], Rm) if True else 1)
    errs.append(abs(stretch - expect) / expect)
    ok(abs(stretch - expect) / expect < 1e-9, f"A1 tets, {name}: stretch {stretch:.6e}, closed form {expect:.6e}")
    vm, sig, vol = fem.stresses(nodes, [{"kind": "tet", "conn": m["tets"], "D": D_}], Diso, u)
    ok(np.allclose(sig[:, 0], sigma, atol=1e-6) and np.abs(sig[:, 1:]).max() < 1e-6, f"A1 tets, {name}: the stress is the uniform {sigma} in x and nothing else")
ok(max(errs) < 1e-9, "A1: tetrahedra: all three turns match the closed form")
# the same on bricks (the element with incompatible modes)
nodes_h, hc = hex_conn(4, 2, 2, L_, w_, t_)
ff = face_forces_hex(nodes_h, hc, L_, np.array([sigma, 0, 0])) + face_forces_hex(nodes_h, hc, 0.0, np.array([-sigma, 0, 0]))
for name, Rm in (("37 degrees about (1,2,3)", R), ("axes turned about z", rot([0, 0, 1], 30.0))):
    D_ = fem.rotate_D(Dl, Rm)
    K, _d0 = fem.assemble(nodes_h, [{"kind": "hex", "conn": hc, "D": D_}], 1.0, 0.3)
    u = solve_dirichlet(K, ff, rigid_pins(nodes_h, L_, w_, t_))
    a_, b_ = node_at(nodes_h, (0, 0, 0)), node_at(nodes_h, (L_, 0, 0))
    stretch = (u[3 * b_] - u[3 * a_]) / L_
    expect = sigma / closed_form_E([1, 0, 0], Rm)
    ok(abs(stretch - expect) / expect < 1e-6, f"A1 bricks, {name}: stretch {stretch:.6e}, closed form {expect:.6e}")
    # a matrix for each element must give the same as one matrix for the group
    Kp, _ = fem.assemble(nodes_h, [{"kind": "hex", "conn": hc, "D": np.broadcast_to(D_, (len(hc), 6, 6)).copy()}], 1.0, 0.3)
    ok(abs(K - Kp).max() < 1e-9 * abs(K).max(), f"A1 bricks, {name}: a matrix per element gives the stiffness of one matrix for all")
    vm, sig, vol = fem.stresses(nodes_h, [{"kind": "hex", "conn": hc, "D": np.broadcast_to(D_, (len(hc), 6, 6)).copy()}], Diso, u)
    ok(np.allclose(sig[:, 0], sigma, atol=1e-5) and np.abs(sig[:, 1:]).max() < 1e-5, f"A1 bricks, {name}: uniform stress, a matrix per element")

# ------------------------------------------------------------------------------------------------------------------------ A2 equal moduli are isotropic
E_, nu_ = 3000.0, 0.28
Gi = E_ / (2 * (1 + nu_))
Do = fem.orthotropic_matrix(E_, E_, E_, Gi, Gi, Gi, nu_, nu_, nu_)
ok(np.allclose(Do, fem.material_matrix(E_, nu_), rtol=1e-12, atol=1e-9), "A2: equal moduli, the isotropic matrix (to 1e-12)")
K_iso, _ = fem.assemble(nodes, [{"kind": "tet", "conn": m["tets"]}], E_, nu_)
K_ort, _ = fem.assemble(nodes, [{"kind": "tet", "conn": m["tets"], "D": Do}], E_, nu_)
ok(abs(K_iso - K_ort).max() < 1e-10 * abs(K_iso).max(), "A2: and the stiffness matrix of the mesh")
K_ort2, _ = fem.assemble(nodes, [{"kind": "tet", "conn": m["tets"], "D": np.broadcast_to(Do, (len(m["tets"]), 6, 6)).copy()}], E_, nu_)
K_ort3, _ = fem.assemble(nodes, [{"kind": "tet", "conn": m["tets"], "D21": fem.pack_D(np.broadcast_to(Do, (len(m["tets"]), 6, 6)))}], E_, nu_)
ok(abs(K_iso - K_ort2).max() < 1e-10 * abs(K_iso).max() and abs(K_iso - K_ort3).max() < 1e-6 * abs(K_iso).max(), "A2: a matrix per element (as 36 or as 21 float32 numbers) too")
# a rotation of the equal-moduli material changes nothing
ok(np.allclose(fem.rotate_D(Do, R), Do, atol=1e-8), "A2: and turning it changes nothing")

# ------------------------------------------------------------------------------------------------------------------------ A3 cantilever
Lb, wb, tb = 100.0, 10.0, 10.0
mb = tet_mesh(20, 2, 2, Lb, wb, tb)
mq = fem.quadratic(mb)
nq = mq["nodes"]
Eb1, Eb2, Gb = 20000.0, 2000.0, 300.0                                    # stiff along the beam, soft across it and in shear
Db = fem.orthotropic_matrix(Eb1, Eb2, Eb2, Gb, Eb2 / (2 * 1.3), Gb, 0.30, 0.30, 0.30)
K, _ = fem.assemble(nq, [{"kind": "tet", "conn": mq["conn"], "D": Db}], 1.0, 0.3)
clamp = np.where(np.isclose(nq[:, 0], 0.0))[0]
tip = np.where(np.isclose(nq[:, 0], Lb))[0]
P = 100.0
f = np.zeros(3 * len(nq))
f[3 * tip + 2] = -P / len(tip)
u = solve_dirichlet(K, f, (3 * clamp[:, None] + np.arange(3)[None, :]).ravel())
defl = -u[3 * tip + 2].mean()
I = wb * tb ** 3 / 12.0
beam = P * Lb ** 3 / (3 * Eb1 * I)
timo = beam + P * Lb / ((5.0 / 6.0) * Gb * wb * tb)                     # beam theory with the shear deflection (shear factor 5/6)
ok(abs(defl - timo) / timo < 0.08, f"A3: orthotropic cantilever tip {defl:.5f} mm, beam theory with shear {timo:.5f} (pure bending {beam:.5f}), within 8 %")
ok(defl > 1.08 * beam, "A3: and the soft shear is in the result (more than 8 % over pure bending)")
Kiso, _ = fem.assemble(nq, [{"kind": "tet", "conn": mq["conn"]}], Eb1, 0.3)
ui = solve_dirichlet(Kiso, f, (3 * clamp[:, None] + np.arange(3)[None, :]).ravel())
ok(abs(-ui[3 * tip + 2].mean() - defl) / defl > 0.1, "A3: an isotropic material of the same E1 is clearly different (the test can tell)")

# ------------------------------------------------------------------------------------------------------------------------ A4 patch test, a matrix in every layer
mp = tet_mesh(4, 4, 6, 40.0, 40.0, 60.0)
npn = mp["nodes"]
tets = mp["tets"]
cz = npn[tets][:, :, 2].mean(axis=1)
layer = np.floor(cz / 10.0 + 1e-9).astype(int)                         # six layers of elements, 10 mm each
rng = np.random.RandomState(4)
base = fem.rotate_D(Dl, R)
Dper = np.empty((len(tets), 6, 6))
adds = rng.uniform(500.0, 8000.0, size=6)
for k in range(6):
    Dk = base.copy()
    v = np.zeros(6); v[0] = 1.0
    Dk = Dk + adds[k] * np.outer(v, v)                                    # more stiff along x only: D[2, 0] is the same in every layer, so the traction on a layer face is continuous
    Dper[layer == k] = Dk
ok(len({round(float(Dper[layer == k][0][0, 0]), 3) for k in range(6)}) == 6 and np.ptp(Dper[:, 2, 0]) < 1e-9, "A4: six layers with six different matrices and one coupling D[z, x]")
eps = 1e-3
bnd = np.where(np.isclose(npn[:, 0], 0) | np.isclose(npn[:, 0], 40) | np.isclose(npn[:, 1], 0) | np.isclose(npn[:, 1], 40) | np.isclose(npn[:, 2], 0) | np.isclose(npn[:, 2], 60))[0]
K, _ = fem.assemble(npn, [{"kind": "tet", "conn": tets, "D": Dper}], 1.0, 0.3)
dofs = (3 * bnd[:, None] + np.arange(3)[None, :]).ravel()
vals = np.zeros(len(dofs)); vals[0::3] = eps * npn[bnd, 0]               # u = (eps x, 0, 0) on the whole boundary
u = solve_dirichlet(K, np.zeros(3 * len(npn)), dofs, vals)
exact = np.zeros(3 * len(npn)); exact[0::3] = eps * npn[:, 0]
ok(np.abs(u - exact).max() < 1e-10, f"A4: the uniform stretch is reproduced exactly with a different matrix in every layer (largest error {np.abs(u - exact).max():.1e})")
vm, sig, vol = fem.stresses(npn, [{"kind": "tet", "conn": tets, "D": Dper}], Diso, u)
want = eps * Dper[:, :, 0]                                              # the stress of the strain (eps, 0, 0, 0, 0, 0): the first column of each matrix
ok(np.allclose(sig, want, rtol=1e-9, atol=1e-9), "A4: and every layer carries the stress its own matrix gives")

# ------------------------------------------------------------------------------------------------------------------------ A7 a million elements
n = 1_000_000
Rm = rot([1, 1, 0], 20.0)
t0 = time.time()
P21 = np.empty((n, 21), np.float32)
for s in range(0, n, 100_000):
    ang_ = np.linspace(0, 6.28, 100_000) + s * 1e-6
    Rk = np.stack([np.cos(ang_), -np.sin(ang_), np.zeros_like(ang_), np.sin(ang_), np.cos(ang_), np.zeros_like(ang_), np.zeros_like(ang_), np.zeros_like(ang_), np.ones_like(ang_)], axis=1).reshape(-1, 3, 3)
    P21[s:s + 100_000] = fem.pack_D(fem.rotate_D(Dl, Rk))
t_rot = time.time() - t0
t0 = time.time()
tot = 0.0
for s in range(0, n, 4000):
    tot += float(fem.unpack_D(P21[s:s + 4000])[:, 0, 0].sum())
t_unp = time.time() - t0
ok(P21.nbytes <= 90e6, f"A7: the matrices of {n:,} elements are {P21.nbytes / 1e6:.0f} MB as 21 float32 numbers (288 MB as 6 x 6 doubles)")
ok(t_rot < 60 and t_unp < 30, f"A7: turning and packing {n:,} matrices took {t_rot:.1f} s, unpacking them in chunks of 4000 took {t_unp:.1f} s")
ok(np.isfinite(tot) and tot > 0, "A7: the unpacked values are finite")

# ------------------------------------------------------------------------------------------------------------------------ what is not tested yet
print("pending A5 (a slice of a 20 mm cube with 45/-45 degree infill: two equal in-plane eigenvalues, phi near the infill density) - needs the fabric grid (PA-3)")
print("pending A6 (a wall-only slice: one dominant eigenvalue along the wall, phi near 1) - needs the fabric grid (PA-3)")
print("pending R1-R3 (real coupons) - need a printer (PA-5)")

print()
print("FAILED: " + "; ".join(fails) if fails else "all passed")
sys.exit(1 if fails else 0)
