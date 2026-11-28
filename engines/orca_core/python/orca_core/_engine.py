"""The backend that runs the compiled engine (the default of the worker).  The bindings to Orca's code are not written yet (SLC-2); until they
are, this says so in words."""
from . import errors


def run(job, folder, progress, is_cancelled):
    try:
        import _orca_core                                        # noqa: F401  the compiled part
    except ImportError:
        raise errors.EngineMissing("The slicing engine is not built into this copy of OpenPara yet.") from None
    raise errors.EngineMissing("The bindings to the slicing engine are not written yet.")
