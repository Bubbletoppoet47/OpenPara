"""cfd3d_morph.py - the air mesh moved with the part (no Qt): when a structure moves the part, the flow is solved again on the SAME tetrahedra with their nodes moved, so nothing is
meshed again and the numbers of two passes are comparable node by node.

The nodes of the part's walls take the displacement they are given, the nodes on the sides of the box stay, and the nodes between them follow by a smooth interpolation: every
component of the displacement solves the Laplace equation on the mesh (each tetrahedron weighted by the inverse of its volume, so the small elements next to the part, where the
displacement is large, are the stiff ones and move almost like the part).  The result is checked: a tetrahedron that is turned inside out is an error in words (the displacement
is too large for this method), and the worst shrink of a tetrahedron is reported.
"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl

import solid_fem as fem


def tet_volumes(nodes, tets):
    """The signed volume of every tetrahedron (mesh units cubed)."""
    P = np.asarray(nodes, float)[np.asarray(tets, np.int64)]
    return np.einsum("ei,ei->e", np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), P[:, 3] - P[:, 0]) / 6.0


def stiffness(nodes, tets):
    """The matrix K of the Laplace equation with every tetrahedron weighted by 1 / its volume (the volume of the element cancels): sum over elements of grad N_i . grad N_j."""
    nodes = np.asarray(nodes, float)
    tets = np.asarray(tets, np.int64)
    N = len(nodes)
    A = np.concatenate([np.ones((len(tets), 4, 1)), nodes[tets]], axis=2)
    g = np.linalg.inv(A)[:, 1:, :]                                    # (ne, 3, 4): the gradient of the shape function k is the column k
    G = np.einsum("eik,eil->ekl", g, g)
    I = np.repeat(tets[:, :, None], 4, axis=2).ravel()
    J = np.repeat(tets[:, None, :], 4, axis=1).ravel()
    return sp.csr_matrix((G.ravel(), (I, J)), shape=(N, N))


def morph(nodes, tets, moved, D, still, cancel=None):
    """-> the new nodes (N, 3).  moved: node numbers that take the displacement D (len(moved), 3); still: node numbers that stay.  Raises FemError for a mesh that is turned inside out."""
    nodes = np.asarray(nodes, float)
    tets = np.asarray(tets, np.int64)
    moved = np.asarray(moved, np.int64)
    D = np.asarray(D, float).reshape(len(moved), 3)
    N = len(nodes)
    V0 = tet_volumes(nodes, tets)
    fixed = np.zeros(N, bool)
    val = np.zeros((N, 3))
    fixed[np.asarray(still, np.int64)] = True
    fixed[moved] = True
    val[moved] = D
    out = val.copy()
    free = ~fixed
    if free.any():
        K = stiffness(nodes, tets)
        Kff = K[free][:, free].tocsc()
        Kfc = K[free][:, fixed]
        lu = spl.splu(Kff)
        for c in range(3):
            if cancel is not None and cancel():
                raise fem.Cancelled()
            out[free, c] = lu.solve(-(Kfc @ val[fixed, c]))
    new = nodes + out
    V1 = tet_volumes(new, tets)
    if np.any(V1 * np.sign(V0) <= 0):
        n = int((V1 * np.sign(V0) <= 0).sum())
        raise fem.FemError(f"Moving the part would turn {n} tetrahedra of the air inside out: the displacement is too large for the mesh to follow. Use a stiffer part, a lower load, "
                           "or a larger box round the part.")
    return new


def shrink(nodes, new, tets):
    """The smallest ratio of the volume of a tetrahedron after the move to before it (1 = none changed; 0.5 = one lost half of its volume)."""
    return float(np.min(tet_volumes(new, tets) / tet_volumes(nodes, tets)))
