"""Shared linear-solver front end for the FEA and CFD tabs.

solve(A, b) uses the multi-threaded PARDISO solver (package pypardiso) when it is installed and falls back to SciPy's
single-threaded SuperLU otherwise.  set_cores(n) chooses how many threads PARDISO may use (the File menu sets it).
"""
import os

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

_cores = max(1, (os.cpu_count() or 2) - 1)
_state = {"pp": None, "tried": False, "error": "", "used": ""}


def max_cores():
    return os.cpu_count() or 1


def default_cores():
    return max(1, max_cores() - 1)


def get_cores():
    return _cores


def set_cores(n):
    """Choose the number of threads (1 .. all cores).  Takes effect for the next solve."""
    global _cores
    _cores = int(max(1, min(int(n), max_cores())))
    os.environ["MKL_NUM_THREADS"] = str(_cores)
    os.environ["OMP_NUM_THREADS"] = str(_cores)
    pp = _load()
    if pp is not None:
        try:
            pp.set_num_threads(_cores)
        except Exception as ex:                                  # keep the old thread count; never break a solve
            _state["error"] = f"could not set the thread count: {ex}"
    return _cores


def _load():
    if not _state["tried"]:
        _state["tried"] = True
        try:
            from pypardiso.scipy_aliases import pypardiso_solver
            _state["pp"] = pypardiso_solver
            try:
                pypardiso_solver.set_num_threads(_cores)
            except Exception as ex:
                _state["error"] = f"could not set the thread count: {ex}"
        except Exception as ex:                                  # not installed, or MKL cannot load
            _state["pp"] = None
            _state["error"] = f"{type(ex).__name__}: {ex}"
    return _state["pp"]


def status():
    """(is the multi-threaded solver available, one-line text)"""
    pp = _load()
    if pp is not None:
        return True, f"PARDISO (pypardiso), {_cores} of {max_cores()} threads"
    return False, f"SciPy SuperLU, 1 thread (pypardiso not available: {_state['error'] or 'not installed'})"


def solve(A, b):
    """Solve A x = b for a sparse square A.  b may be a vector or a dense matrix.

    If PARDISO fails or returns non-finite numbers (a singular matrix, say) the same system is handed to SuperLU, whose
    MatrixRankWarning the callers already turn into a clear message."""
    pp = _load()
    if pp is not None:
        try:
            x = pp.solve(sp.csr_matrix(A), b)
            if np.all(np.isfinite(x)):
                _state["used"] = "pardiso"
                return x
        except Exception as ex:
            _state["error"] = f"{type(ex).__name__}: {ex}"
    _state["used"] = "superlu"
    return spla.spsolve(sp.csc_matrix(A), b)


def last_used():
    return _state["used"]
