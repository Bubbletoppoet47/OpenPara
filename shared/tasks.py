"""Progress and cancel hooks shared by the mesh operations.

An operation takes `progress=None`; when given it is called as progress(stage_text, fraction_or_None) from the working thread, and it may
raise Cancelled to stop the work (the viewer's Cancel button does this).  sub() maps a stage's own 0..1 into a slice of the whole.
"""


class Cancelled(Exception):
    pass


def tick(progress, stage, frac=None):
    if progress:
        progress(stage, frac)


def sub(progress, lo, hi):
    """A progress callback for a stage that covers [lo, hi] of the whole job."""
    if progress is None:
        return None

    def f(stage, frac=None):
        progress(stage, None if frac is None else lo + (hi - lo) * min(max(frac, 0.0), 1.0))
    return f
