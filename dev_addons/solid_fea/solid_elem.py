"""
solid_elem.py - the hexahedra and pyramids of the hex-dominant mesh of the 3D FEA add-on (no window).

  hex8 / hex20     8-node and 20-node (serendipity) hexahedra in VTK node order.  The 8-node one has the incompatible bending modes of Wilson and Taylor
                   (a block of plain 8-node bricks is far too stiff in bending); the 20-node one is integrated with 3 x 3 x 3 points.
  pyr5 / pyr13     pyramids (VTK order: the four base corners, then the apex; the 13-node one adds the mid-edge nodes of the base edges, then of the four
                   edges that run up to the apex).  A pyramid is the hexahedron whose top face is collapsed onto the apex, so one set of routines does both;
                   the nodes that fall together share their degrees of freedom.

A "group" of the mesh is {"kind": "tet" | "hex" | "pyr", "conn": (n, nodes per element)} (the tetrahedra are in solid_fem).
Everything here works on arrays of elements: coordinates X (n, nodes, 3) in, matrices / stresses out.
"""
import numpy as np

CORNERS = np.array([(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)], float)
MIDS = np.array([(0, -1, -1), (1, 0, -1), (0, 1, -1), (-1, 0, -1), (0, -1, 1), (1, 0, 1), (0, 1, 1), (-1, 0, 1),
                 (-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], float)
HEX_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]        # the mid-edge nodes 8..19 of a hex20
PYR_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]                                         # the mid-edge nodes 5..12 of a pyr13
PYR_MAP = {1: np.array([0, 1, 2, 3, 4, 4, 4, 4]),
           2: np.array([0, 1, 2, 3, 4, 4, 4, 4, 5, 6, 7, 8, 4, 4, 4, 4, 9, 10, 11, 12])}      # node k of the collapsed hexahedron = node PYR_MAP[k] of the pyramid
NODES = {("hex", 1): 8, ("hex", 2): 20, ("pyr", 1): 5, ("pyr", 2): 13}


class ElementError(Exception):
    pass


def gauss(n):
    x, w = np.polynomial.legendre.leggauss(n)
    pts = np.array([(a, b, c) for a in x for b in x for c in x])
    wt = np.array([wa * wb * wc for wa in w for wb in w for wc in w])
    return pts, wt


def shape(order, pts):
    """Shape functions N (np, nodes) and their derivatives with respect to the reference coordinates dN (np, nodes, 3) at the points (np, 3)."""
    pts = np.atleast_2d(np.asarray(pts, float))
    x, y, z = pts[:, 0:1], pts[:, 1:2], pts[:, 2:3]
    if order == 1:
        c = CORNERS
        a, b, d = c[:, 0][None], c[:, 1][None], c[:, 2][None]
        fx, fy, fz = 1 + a * x, 1 + b * y, 1 + d * z
        N = 0.125 * fx * fy * fz
        dN = np.stack([0.125 * a * fy * fz, 0.125 * b * fx * fz, 0.125 * d * fx * fy], axis=2)
        return N, dN
    allc = np.vstack([CORNERS, MIDS])
    a, b, d = allc[:, 0][None], allc[:, 1][None], allc[:, 2][None]
    fx, fy, fz = 1 + a * x, 1 + b * y, 1 + d * z
    n = len(allc)
    N = np.zeros((len(pts), n))
    dN = np.zeros((len(pts), n, 3))
    cor = np.arange(8)
    s = (a * x + b * y + d * z)[:, cor]
    N[:, cor] = 0.125 * fx[:, cor] * fy[:, cor] * fz[:, cor] * (s - 2)
    dN[:, cor, 0] = 0.125 * a[:, cor] * fy[:, cor] * fz[:, cor] * (2 * a[:, cor] * x + b[:, cor] * y + d[:, cor] * z - 1)
    dN[:, cor, 1] = 0.125 * b[:, cor] * fx[:, cor] * fz[:, cor] * (a[:, cor] * x + 2 * b[:, cor] * y + d[:, cor] * z - 1)
    dN[:, cor, 2] = 0.125 * d[:, cor] * fx[:, cor] * fy[:, cor] * (a[:, cor] * x + b[:, cor] * y + 2 * d[:, cor] * z - 1)
    for sel, ax in ((np.arange(8, 20)[allc[8:, 0] == 0], 0), (np.arange(8, 20)[allc[8:, 1] == 0], 1), (np.arange(8, 20)[allc[8:, 2] == 0], 2)):
        if ax == 0:
            N[:, sel] = 0.25 * (1 - x ** 2) * fy[:, sel] * fz[:, sel]
            dN[:, sel, 0] = -0.5 * x * fy[:, sel] * fz[:, sel]
            dN[:, sel, 1] = 0.25 * (1 - x ** 2) * b[:, sel] * fz[:, sel]
            dN[:, sel, 2] = 0.25 * (1 - x ** 2) * fy[:, sel] * d[:, sel]
        elif ax == 1:
            N[:, sel] = 0.25 * (1 - y ** 2) * fx[:, sel] * fz[:, sel]
            dN[:, sel, 0] = 0.25 * (1 - y ** 2) * a[:, sel] * fz[:, sel]
            dN[:, sel, 1] = -0.5 * y * fx[:, sel] * fz[:, sel]
            dN[:, sel, 2] = 0.25 * (1 - y ** 2) * fx[:, sel] * d[:, sel]
        else:
            N[:, sel] = 0.25 * (1 - z ** 2) * fx[:, sel] * fy[:, sel]
            dN[:, sel, 0] = 0.25 * (1 - z ** 2) * a[:, sel] * fy[:, sel]
            dN[:, sel, 1] = 0.25 * (1 - z ** 2) * fx[:, sel] * b[:, sel]
            dN[:, sel, 2] = -0.5 * z * fx[:, sel] * fy[:, sel]
    return N, dN


_TABLES = {}


def tables(order, n):
    """(N, dN, weights) at the n x n x n Gauss points."""
    k = (order, n)
    if k not in _TABLES:
        pts, w = gauss(n)
        N, dN = shape(order, pts)
        _TABLES[k] = (N, dN, w)
    return _TABLES[k]


def rule(kind, order):
    """Points per direction: the 8-node brick 2 (with its incompatible modes), everything else 3 (the collapsed pyramids need the extra points)."""
    return 2 if (kind == "hex" and order == 1) else 3


def as_hex(kind, conn):
    """The connectivity as hexahedra: a pyramid becomes the collapsed hexahedron (the apex is repeated)."""
    if kind == "hex":
        return conn
    return conn[:, PYR_MAP[2 if conn.shape[1] == 13 else 1]]


def order_of(kind, conn):
    return 2 if conn.shape[1] in (20, 13) else 1


def bmat(g):
    """g (ne, nodes, 3) gradients of the shape functions -> B (ne, 6, 3 nodes)  (strain order xx yy zz xy yz xz, engineering shear)."""
    ne, nne = g.shape[0], g.shape[1]
    B = np.zeros((ne, 6, 3 * nne))
    for i in range(nne):
        gx, gy, gz = g[:, i, 0], g[:, i, 1], g[:, i, 2]
        B[:, 0, 3 * i] = gx
        B[:, 1, 3 * i + 1] = gy
        B[:, 2, 3 * i + 2] = gz
        B[:, 3, 3 * i], B[:, 3, 3 * i + 1] = gy, gx
        B[:, 4, 3 * i + 1], B[:, 4, 3 * i + 2] = gz, gy
        B[:, 5, 3 * i], B[:, 5, 3 * i + 2] = gz, gx
    return B


def _jac(X, dN):
    """J (ne, 3, 3) with J[a, b] = d x_b / d xi_a, its determinant and inverse; an element that is turned inside out is an ElementError."""
    J = np.einsum("ia,eib->eab", dN, X)
    det = np.linalg.det(J)
    if not (det > 0).all():
        raise ElementError(f"{int((~(det > 0)).sum())} hexahedra or pyramids are inverted or flat (the mesh is not usable).")
    return J, det, np.linalg.inv(J)


def _grads(Jinv, dN):
    return np.einsum("eba,ia->eib", Jinv, dN)                       # (ne, nodes, 3): d N_i / d x_b


_INC = lambda p: np.array([[-2 * p[0], 0, 0], [0, -2 * p[1], 0], [0, 0, -2 * p[2]]])        # derivatives of the modes 1-xi^2, 1-eta^2, 1-zeta^2


def _inc_parts(X, D, order_pts):
    """Wilson-Taylor incompatible modes of a 8-node brick: the matrices needed for the condensed stiffness and for the stresses.
    Returns Kuu (ne,24,24), Kua (ne,24,9), Kaa (ne,9,9), volume (ne,)."""
    N, dN, w = tables(1, 2)
    pts, _w = gauss(2)
    _N0, dN0 = shape(1, np.zeros((1, 3)))
    J0, det0, Ji0 = _jac(X, dN0[0])
    ne = len(X)
    Kuu = np.zeros((ne, 24, 24))
    Kua = np.zeros((ne, 24, 9))
    Kaa = np.zeros((ne, 9, 9))
    vol = np.zeros(ne)
    for p, dn, wi in zip(pts, dN, w):
        J, det, Ji = _jac(X, dn)
        B = bmat(_grads(Ji, dn))
        Bi = bmat(np.einsum("eba,ma->emb", Ji0, _INC(p)) * (det0 / det)[:, None, None])
        wd = (wi * det)[:, None, None]
        DB, DBi = D @ B, D @ Bi
        Kuu += wd * (B.transpose(0, 2, 1) @ DB)
        Kua += wd * (B.transpose(0, 2, 1) @ DBi)
        Kaa += wd * (Bi.transpose(0, 2, 1) @ DBi)
        vol += wi * det
    return Kuu, Kua, Kaa, vol


def stiffness(kind, X, D):
    """Element stiffness matrices (ne, 3 nodes, 3 nodes) of hexahedra / pyramids; X are the coordinates of the HEXAHEDRON nodes (pyramids: collapsed)."""
    order = 2 if X.shape[1] == 20 else 1
    if kind == "hex" and order == 1:
        Kuu, Kua, Kaa, _v = _inc_parts(X, D, 2)
        return Kuu - Kua @ np.linalg.solve(Kaa, Kua.transpose(0, 2, 1))
    N, dN, w = tables(order, 3)
    K = np.zeros((len(X), 3 * X.shape[1], 3 * X.shape[1]))
    for dn, wi in zip(dN, w):
        J, det, Ji = _jac(X, dn)
        B = bmat(_grads(Ji, dn))
        K += (wi * det)[:, None, None] * (B.transpose(0, 2, 1) @ (D @ B))
    return K


_E0 = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])                    # a thermal strain is the same in every normal direction and has no shear


def _inc_thermal(X, D, e0):
    """The thermal load of the 8-node brick in its two parts: on the displacement modes (ne, 24) and on the incompatible modes (ne, 9).
    e0 (ne, 8): the thermal strain alpha (T - Tref) at the nodes."""
    N, dN, w = tables(1, 2)
    pts, _w = gauss(2)
    _N0, dN0 = shape(1, np.zeros((1, 3)))
    J0, det0, Ji0 = _jac(X, dN0[0])
    ne = len(X)
    fu, fa = np.zeros((ne, 24)), np.zeros((ne, 9))
    for p, n, dn, wi in zip(pts, N, dN, w):
        J, det, Ji = _jac(X, dn)
        B = bmat(_grads(Ji, dn))
        Bi = bmat(np.einsum("eba,ma->emb", Ji0, _INC(p)) * (det0 / det)[:, None, None])
        Ds0 = ((e0 @ n)[:, None] * _E0[None, :]) @ D.T
        fu += (wi * det)[:, None] * np.einsum("eri,er->ei", B, Ds0)
        fa += (wi * det)[:, None] * np.einsum("eri,er->ei", Bi, Ds0)
    return fu, fa


def thermal_forces(kind, X, D, e0):
    """Consistent nodal forces (ne, nodes, 3) of a thermal strain: e0 (ne, nodes) is alpha (T - Tref) at the nodes of every element, the same in x, y and z
    (the 8-node brick condenses its incompatible modes out, exactly as its stiffness does)."""
    order = 2 if X.shape[1] == 20 else 1
    ne, nn = X.shape[0], X.shape[1]
    if kind == "hex" and order == 1:
        fu, fa = _inc_thermal(X, D, e0)
        Kuu, Kua, Kaa, _v = _inc_parts(X, D, 2)
        f = fu - np.einsum("eia,ea->ei", Kua, np.linalg.solve(Kaa, fa[:, :, None])[:, :, 0])
        return f.reshape(ne, nn, 3)
    N, dN, w = tables(order, 3)
    f = np.zeros((ne, 3 * nn))
    for n, dn, wi in zip(N, dN, w):
        J, det, Ji = _jac(X, dn)
        B = bmat(_grads(Ji, dn))
        Ds0 = ((e0 @ n)[:, None] * _E0[None, :]) @ D.T
        f += (wi * det)[:, None] * np.einsum("eri,er->ei", B, Ds0)
    return f.reshape(ne, nn, 3)


def recover(kind, X, D, ue, e0=None, energy=False):
    """Per element: the largest von Mises stress at the integration points, the volume-weighted mean stress (ne, 6) and the volume.
    ue (ne, 3 nodes): the element's displacements.  e0 (ne, nodes): the thermal strain alpha (T - Tref) at the nodes (None: no temperature); the stress then comes from
    the strain that is not thermal.  energy=True also returns the elastic strain energy of every element (half the integral of strain-minus-thermal-strain . stress)."""
    order = 2 if X.shape[1] == 20 else 1
    ne = len(X)
    vmax = np.zeros(ne)
    mean = np.zeros((ne, 6))
    vol = np.zeros(ne)
    en = np.zeros(ne)

    def point(strain, n, wd):
        nonlocal vmax, mean, vol, en
        if e0 is not None:
            strain = strain - (e0 @ n)[:, None] * _E0[None, :]
        sg = strain @ D.T
        vmax = np.maximum(vmax, vm(sg))
        mean += wd[:, None] * sg
        vol += wd
        en += 0.5 * wd * np.einsum("er,er->e", strain, sg)

    if kind == "hex" and order == 1:
        Kuu, Kua, Kaa, _v = _inc_parts(X, D, 2)
        rhs = -np.einsum("eia,ei->ea", Kua, ue)
        if e0 is not None:
            rhs = rhs + _inc_thermal(X, D, e0)[1]
        alpha = np.linalg.solve(Kaa, rhs[:, :, None])[:, :, 0]
        pts, _w = gauss(2)
        N, dN, w = tables(1, 2)
        _N0, dN0 = shape(1, np.zeros((1, 3)))
        J0, det0, Ji0 = _jac(X, dN0[0])
        for p, n, dn, wi in zip(pts, N, dN, w):
            J, det, Ji = _jac(X, dn)
            B = bmat(_grads(Ji, dn))
            Bi = bmat(np.einsum("eba,ma->emb", Ji0, _INC(p)) * (det0 / det)[:, None, None])
            point(np.einsum("eri,ei->er", B, ue) + np.einsum("eri,ei->er", Bi, alpha), n, wi * det)
    else:
        N, dN, w = tables(order, 3)
        for n, dn, wi in zip(N, dN, w):
            J, det, Ji = _jac(X, dn)
            B = bmat(_grads(Ji, dn))
            point(np.einsum("eri,ei->er", B, ue), n, wi * det)
    out = (vmax, mean / vol[:, None], vol)
    return out + (en,) if energy else out


def body_forces(kind, X, b):
    """Consistent nodal forces (ne, nodes, 3) of a uniform body force vector b (N/mm3)."""
    order = 2 if X.shape[1] == 20 else 1
    N, dN, w = tables(order, 3)
    f = np.zeros((len(X), X.shape[1], 3))
    for n, dn, wi in zip(N, dN, w):
        J, det, Ji = _jac(X, dn)
        f += (wi * det)[:, None, None] * n[None, :, None] * np.asarray(b, float)[None, None, :]
    return f


def volumes(kind, X):
    """Element volumes (the exact integral of the trilinear / serendipity map)."""
    order = 2 if X.shape[1] == 20 else 1
    N, dN, w = tables(order, 3)
    v = np.zeros(len(X))
    for dn, wi in zip(dN, w):
        J, det, Ji = _jac(X, dn)
        v += wi * det
    return v


def vm(s):
    return np.sqrt(np.maximum(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2) + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2), 0))


def orient_pyramids(nodes, pyr):
    """Pyramids with the nodes in VTK order: the base corners counter-clockwise seen from the apex, the apex last (the base normal by the right-hand rule
    points to the apex).  Swaps two base nodes where it is the other way round."""
    if not len(pyr):
        return pyr
    P = nodes[pyr[:, :5]]
    n = np.cross(P[:, 2] - P[:, 0], P[:, 3] - P[:, 1])
    up = np.einsum("ij,ij->i", n, P[:, 4] - P[:, :4].mean(axis=1)) > 0
    out = pyr.copy()
    flip = ~up
    out[flip] = pyr[flip][:, [0, 3, 2, 1, 4]]
    return out


def split_volume(nodes, pyr):
    """The volume of straight-sided pyramids as two tetrahedra (a check that does not use the shape functions)."""
    P = nodes[pyr[:, :5]]
    sv = lambda c: np.einsum("ij,ij->i", c[:, 1] - c[:, 0], np.cross(c[:, 2] - c[:, 0], c[:, 3] - c[:, 0])) / 6.0
    return sv(P[:, [0, 1, 2, 4]]) + sv(P[:, [0, 2, 3, 4]])
