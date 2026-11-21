"""ctl_section.py - what every section of the Controls tab shares: the Section base class and the axis-tick helpers (no Qt widgets of its own)."""
import math

from PyQt6.QtWidgets import QWidget


def nice_step(span, n=6):
    """A round step (1, 2, 2.5, 5 x a power of ten) that puts about n ticks across `span`."""
    raw = max(span, 1e-12) / n
    mag = 10 ** math.floor(math.log10(raw))
    for s in (1, 2, 2.5, 5, 10):
        if s * mag >= raw:
            return s * mag
    return 10 * mag


def ticks(lo, hi):
    step = nice_step(hi - lo)
    v = math.ceil(lo / step - 1e-9) * step
    out = []
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


class Section:
    """One tool.  `inputs` goes in the left column (shown when the section is open); `results` is its page on the right."""
    key = "section"
    title = "Section"

    def __init__(self, changed):
        self.changed = changed                      # call when an input was edited
        self.inputs = QWidget()
        self.results = QWidget()
        self.tab = None                             # set by the tab, so a section can send its answer to another one

    def to_json(self):
        return {}

    def from_json(self, d):
        pass
