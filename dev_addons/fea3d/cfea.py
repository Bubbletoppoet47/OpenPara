"""cfea.py - Python side of the native FEA kernels (native/cfea.c via ctypes).  Everything here is optional: `available()` is False when the
library for this platform is missing or will not load, and the callers then use their numpy code (same results, slower)."""
import ctypes
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_lib = None
_tried = False
VERSION = 3


def _load():
    global _lib, _tried
    if _tried:
        return _lib
    _tried = True
    if os.environ.get("OPENPARA_NO_NATIVE"):
        return None
    name = "cfea.dll" if sys.platform.startswith("win") else "cfea.dylib" if sys.platform == "darwin" else "cfea.so"
    path = os.path.join(HERE, "native", name)
    try:
        lib = ctypes.CDLL(path)
        lib.cfea_version.restype = ctypes.c_int
        if lib.cfea_version() != VERSION:
            return None
        c_d, c_i = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int32)
        lib.cfea_assemble.restype = ctypes.c_int64
        lib.cfea_assemble.argtypes = [ctypes.c_int, ctypes.c_int64, c_d, c_i, c_d, c_d, c_i, c_i, c_d]
        lib.cfea_centre_strain.restype = None
        lib.cfea_centre_strain.argtypes = [ctypes.c_int, ctypes.c_int64, c_d, c_i, c_d, c_d]
        lib.cfea_threads.restype = ctypes.c_int
        lib.cfea_set_threads.argtypes = [ctypes.c_int]
        _lib = lib
    except Exception:                                        # noqa: BLE001  (missing file, wrong platform, ...)
        _lib = None
    return _lib


def available():
    return _load() is not None


def threads():
    lib = _load()
    return lib.cfea_threads() if lib else 1


def set_threads(n):
    lib = _load()
    if lib:
        lib.cfea_set_threads(int(n))


def _p(a, ct):
    return a.ctypes.data_as(ctypes.POINTER(ct))


def _check(nodes, conn, order):
    if conn.shape[1] != (10 if order == 2 else 4) or nodes.ndim != 2 or nodes.shape[1] != 3:
        raise ValueError("native kernels: unexpected array shapes")
    if conn.size and (conn.min() < 0 or conn.max() >= len(nodes)):
        raise ValueError("native kernels: element connectivity points outside the node list")


def node_pattern(conn, nn):
    """Sorted node-level CSR pattern (indptr, indices) of the elements' node couplings."""
    import scipy.sparse as sp
    ne, k = conn.shape
    A = sp.csr_matrix((np.ones(ne * k, np.int32), conn.ravel(), np.arange(0, ne * k + 1, k)), shape=(ne, nn))
    S = (A.T.tocsr() @ A).tocsr()
    S.sort_indices()
    return S.indptr.astype(np.int32), S.indices.astype(np.int32)


def assemble(nodes, conn, order, D, nn, scale=None, pattern=None):
    """-> scipy CSR stiffness matrix (3 nn x 3 nn).  `pattern` = node_pattern(...) can be reused for repeated assemblies (nonlinear iterations)."""
    import scipy.sparse as sp
    lib = _load()
    nptr, nidx = pattern if pattern is not None else node_pattern(conn, nn)
    nodes = np.ascontiguousarray(nodes, np.float64)
    conn = np.ascontiguousarray(conn, np.int32)
    _check(nodes, conn, order)
    D = np.ascontiguousarray(D, np.float64)
    sc = None if scale is None else np.ascontiguousarray(scale, np.float64)
    data = np.zeros(9 * len(nidx))
    bad = lib.cfea_assemble(order, conn.shape[0], _p(nodes, ctypes.c_double), _p(conn, ctypes.c_int32), _p(D, ctypes.c_double),
                            None if sc is None else _p(sc, ctypes.c_double), _p(nptr, ctypes.c_int32), _p(nidx, ctypes.c_int32), _p(data, ctypes.c_double))
    # dof-level CSR from the node pattern: dof row 3i+a starts at 9*nptr[i] + a*3*k_i and holds, for each node column j in order, entries 3j .. 3j+2
    k = np.diff(nptr).astype(np.int64)
    starts = (9 * nptr[:-1, None].astype(np.int64) + np.arange(3)[None, :] * 3 * k[:, None]).ravel()
    indptr = np.append(starts, 9 * int(nptr[-1])).astype(np.int64)
    indices = np.empty(9 * len(nidx), np.int32)
    row_start = np.repeat(9 * nptr[:-1].astype(np.int64), k)                     # start of the node row of each node entry
    row_k = np.repeat(k, k)
    pos = np.arange(len(nidx)) - np.repeat(nptr[:-1].astype(np.int64), k)        # position of the entry inside its node row
    for a in range(3):
        dst = row_start + a * 3 * row_k + 3 * pos
        for b in range(3):
            indices[dst + b] = 3 * nidx + b
    K = sp.csr_matrix((data, indices, indptr), shape=(3 * nn, 3 * nn))
    K.eliminate_zeros()                                   # same stored entries as the numpy path
    return K, bad, (nptr, nidx)


def centre_strain(nodes, conn, order, u):
    lib = _load()
    nodes = np.ascontiguousarray(nodes, np.float64)
    conn = np.ascontiguousarray(conn, np.int32)
    _check(nodes, conn, order)
    u = np.ascontiguousarray(u, np.float64).ravel()
    if u.size != 3 * len(nodes):
        raise ValueError(f'displacement vector has {u.size} entries, expected {3 * len(nodes)}')
    eps = np.zeros((conn.shape[0], 6))
    lib.cfea_centre_strain(order, conn.shape[0], _p(nodes, ctypes.c_double), _p(conn, ctypes.c_int32), _p(u, ctypes.c_double), _p(eps, ctypes.c_double))
    return eps
