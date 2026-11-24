"""solid_progress.py - the progress bar of the 3D FEA window: how far along a mesh or a solve is, how long it has taken and how long it will probably take.

What can be known.  The solver goes through a few stages (mesh, assemble the stiffness matrix, solve, stresses).  Some of them know their own progress
(the assembly works through the elements in chunks; the iterative solver has a residual that falls).  The big one,
the direct factorisation of the stiffness matrix (95 % of the time of a typical solve), is ONE call into a library that reports nothing while it runs, so
for that stage the bar is a time estimate: the cost grows with the number of unknowns and with the thickness of the part, and the constant for this
computer is learned from the solves it has done before (solid_timing.json in the user folder).  The first solve on a computer uses the speed of its own
assembly stage as the yardstick.  The bar says "(estimate)" next to the time left, never reaches 100 % before the work is done, and when a stage takes
longer than estimated it creeps slowly towards the end and says so instead of pretending.

Tracker is what the solver code is handed as its `progress` argument.  It is still a function of one text (the old interface: the text shown in the
status line), and it has the extra methods stage(), part() that solid_fem calls through getattr, so any plain function still works as `progress`.
It is written to by the worker thread and read by the window's timer; the arithmetic needs no Qt (the tests run it with a fake clock).

ProgressRow is the widget: a bar and a line of text under the Solve button, hidden while nothing runs."""
import json
import math
import os
import statistics
import threading
import time

# ---------------------------------------------------------------------------------------------------------------------------- the time model
# seconds = fixed + c * size.  The size of a stage and the default c (measured on a Linux VM; the learned value for the real computer replaces it).
STAGES = {
    "mesh": (0.15, 3.0e-5),          # size: elements (the estimate before the mesh exists)
    "meshhex": (0.5, 3.0e-4),        # hex-dominant mesh: slower and less predictable
    "assemble": (0.02, 6.5e-5),      # size: elements
    "factor": (0.05, 2.0e-8),        # size: factor_cost() of the direct solve of a body held in place
    "ilu": (0.1, 3.5e-7),            # the multigrid setup that precedes the iterative solver; size: non-zeros of the matrix (18 s for 60 million)
    "cg": (0.1, 2.5e-4),             # the iterations themselves (their progress is measured); size: unknowns (about 135 iterations of 2e-6 s per unknown)
    "stress": (0.02, 1.2e-5),        # size: elements
    "other": (1.0, 0.0),             # a stage nobody has a name for
}
LEARN = ("mesh", "meshhex", "assemble", "factor", "ilu", "cg", "stress")        # the stages whose time is kept for next time
MIN_LEARN_S = 0.25                   # a stage shorter than this says nothing about the speed of the computer
SPEED_KEYS = ("mesh", "meshhex", "factor", "ilu", "cg", "stress")       # the stages scaled by the speed measured in the assembly of this solve
ELEMENT_FACTOR = 0.19                # elements ~ volume / (ELEMENT_FACTOR * h^3) for the quadratic tetrahedra of the automatic mesh (measured: 0.17 to 0.20)
NODES_PER_ELEMENT = 1.7              # quadratic tetrahedra
NNZ_PER_UNKNOWN = 80.0               # the stiffness matrix of quadratic tetrahedra
ON_TIME = 0.96                       # how far through a stage the bar is when its estimated time is up (it jumps to the end when the stage really ends)
ORDER = {"mesh": 0, "meshhex": 0, "assemble": 1, "factor": 2, "ilu": 2, "cg": 3, "stress": 4}        # the order the stages come in
CEILING = 0.995                      # the bar never shows more than this before the work is finished
DIRECT_LIMIT = 40000                 # the same number as solid_fem.DIRECT_LIMIT (the largest system that is solved directly; a test checks they agree)


def factor_cost(unknowns, extent=None):
    """What the direct factorisation of a body with this many unknowns costs, in units of the table above.  A direct solver is cheap on a long thin bar and
    expensive on a fat block, so the thickness matters as much as the count: the cost is (nodes) x (nodes in the thinnest cross-section)^2, the cross-section
    being the two smaller sides of the bounding box (extent = the three sides) at the node spacing that `unknowns` implies."""
    n = max(float(unknowns) / 3.0, 1.0)
    if extent is None:
        m = n ** (2.0 / 3.0)
    else:
        a, b, c = sorted((max(float(x), 0.0) for x in extent), reverse=True)
        a = max(a, 1e-12)
        b, c = max(b, 1e-6 * a), max(c, 1e-6 * a)
        m = b * c * (n / (a * b * c)) ** (2.0 / 3.0)
    return n * max(m, 1.0) ** 2


def estimate_elements(volume, h):
    return max(float(volume) / (ELEMENT_FACTOR * float(h) ** 3), 1.0) if h and volume else 1000.0


def estimate_for(geom, h, body_h=None):
    """The number of elements to expect: from the volume and the element size; for an assembly whose parts have sizes of their own
    (body_h = {body index: mm}), part by part, each at its own size (the parts without one at `h`)."""
    bodies = (geom or {}).get("bodies")
    if body_h and bodies:
        own = {int(k): float(v) for k, v in body_h.items()}
        return sum(estimate_elements(b.get("volume"), own.get(i, h)) for i, b in enumerate(bodies))
    return estimate_elements((geom or {}).get("volume"), h)


def fmt_time(s, fine=False):
    """12 s, 2 min 05 s, 1 h 03 min.  fine=True gives a tenth of a second under 10 s (the time a finished job took)."""
    s = max(float(s), 0.0)
    if fine and s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{int(s)} s"
    m, sec = divmod(int(s), 60)
    if m < 60:
        return f"{m} min {sec:02d} s"
    return f"{m // 60} h {m % 60:02d} min"


def fmt_left(s):
    """'about 40 s' - a rounded figure, because the estimate is not good to the second."""
    s = max(float(s), 0.0)
    if s < 4:
        return "a few seconds"
    if s < 20:
        return f"about {int(round(s))} s"
    if s < 90:
        return f"about {int(round(s / 5.0)) * 5} s"
    if s < 3600:
        m = s / 60.0
        return f"about {m:.0f} min" if m >= 5 else f"about {m:.1f} min".replace(".0 min", " min")
    return f"about {s / 3600.0:.1f} h"


# ---------------------------------------------------------------------------------------------------------------------------- what the computer has done before
class History:
    """{stage: [seconds per unit of size, ...]} of the last solves on this computer, kept in solid_timing.json in the user folder."""
    FILE = "solid_timing.json"
    KEEP = 12
    USE = 6

    def __init__(self, path=None):
        self.path = path if path is not None else self.default_path()
        self.data = {}
        if self.path:
            try:
                with open(self.path, encoding="utf-8") as f:
                    d = json.load(f)
                self.data = {k: [float(x) for x in v if x > 0] for k, v in (d.get("c") or {}).items() if isinstance(v, list)}
            except (OSError, ValueError, TypeError, AttributeError):
                self.data = {}

    @classmethod
    def default_path(cls):
        try:
            import paths
            return os.path.join(paths.user_dir(), cls.FILE)
        except Exception:
            return None

    def add(self, key, c):
        if c > 0 and math.isfinite(c):
            v = self.data.setdefault(key, [])
            v.append(float(c))
            del v[:-self.KEEP]

    def c(self, key):
        v = self.data.get(key)
        return statistics.median(v[-self.USE:]) if v else None

    def save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"v": 1, "c": self.data}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------------------------------------- the tracker
class Tracker:
    """The `progress` argument of the solver: tracker(text), tracker.stage(key, size), tracker.part(fraction)."""

    def __init__(self, history=None, clock=time.monotonic, emit=None):
        self.history = history if history is not None else History()
        self.clock = clock
        self.emit = emit                         # called with the text of every message (the status line of the window)
        self.lock = threading.Lock()
        self.t0 = clock()
        self.label = "Starting"
        self.done = []                           # [(key, size, seconds)] of the stages that are over
        self.cur = None                          # the stage that is running: {"key", "size", "t0", "pred", "frac", "label"}
        self.future = []                         # [(key, size)] the stages that probably follow
        self.speed = None                        # this computer against the machine of the table, from the assembly of this solve
        self.last = 0.0
        self.cancelling = False
        self.cyclic = False                      # the plan repeats stages (the loops of an adaptive mesh): a stage that begins only takes its own place out of the plan
        self.finished = None                     # None while running; True / False when over
        self.total = None

    # ------------------------------------------------------------------ what the solver tells
    def __call__(self, text):
        with self.lock:
            self.label = str(text)
        fn = self.emit
        if fn is not None:
            fn(str(text))

    def attach(self, emit):
        self.emit = emit

    def expect(self, stages, cyclic=False):
        """[(key, size)]: the stages that a run like this one will go through (an estimate from the size of the model), so the bar knows the whole
        job from the first second.  Each real stage that begins replaces its place in this plan.  cyclic: the plan goes through the same stages
        several times (the loops of an adaptive mesh), so a stage that begins does not drop the later stages of an earlier kind."""
        with self.lock:
            self.cyclic = bool(cyclic)
            self.future = [(k, float(s)) for k, s in stages]

    def stage(self, key, size=0.0):
        with self.lock:
            now = self.clock()
            self._close(now)
            size = float(size or 0.0)
            o = ORDER.get(key)
            if o is not None and not self.cyclic:                      # the plan was a guess: what this stage has passed or replaced is no longer expected
                self.future = [(k, s_) for k, s_ in self.future if ORDER.get(k, 99) > o or (ORDER.get(k) == o and k == key)]
            for i, (k, _s) in enumerate(self.future):                  # this stage was planned: its place in the plan is taken
                if k == key:
                    del self.future[i]
                    break
            self.cur = {"key": key, "size": size, "t0": now, "pred": self._predict(key, size), "frac": None, "label": self.label}

    def part(self, fraction):
        """The real progress of the running stage, 0..1 (the work it has done, as far as the stage itself can tell)."""
        try:
            f = float(fraction)
        except (TypeError, ValueError):
            return
        with self.lock:
            if self.cur is not None and math.isfinite(f):
                f = min(max(f, 0.0), 1.0)
                self.cur["frac"] = f if self.cur["frac"] is None else max(self.cur["frac"], f)

    def finish(self, ok=True):
        with self.lock:
            now = self.clock()
            self._close(now, learn=ok)
            self.finished = bool(ok)
            self.total = now - self.t0
            self.future = []
            if ok:
                self.history.save()

    # ------------------------------------------------------------------ the arithmetic
    def _predict(self, key, size):
        fixed, c0 = STAGES.get(key, STAGES["other"])
        c = self.history.c(key)
        if c is None:
            c = c0 * (self.speed if (self.speed and key in SPEED_KEYS) else 1.0)
        return fixed + c * size

    def _close(self, now, learn=True):
        cur, self.cur = self.cur, None
        if cur is None:
            return
        dur = now - cur["t0"]
        self.done.append((cur["key"], cur["size"], dur))
        if cur["key"] == "assemble" and dur >= 0.1 and cur["size"] > 0:            # the yardstick for the stages that have no history on this computer yet
            ref = STAGES["assemble"][0] + STAGES["assemble"][1] * cur["size"]
            self.speed = min(max(dur / ref, 0.4), 3.0)
        if learn and cur["key"] in LEARN and cur["size"] > 0 and dur >= MIN_LEARN_S:
            self.history.add(cur["key"], max(dur - STAGES[cur["key"]][0], 1e-9) / cur["size"])

    def snapshot(self):
        """(fraction 0..1, text, details): where the work stands now."""
        with self.lock:
            now = self.clock()
            elapsed = now - self.t0
            if self.finished is not None:
                text = f"Done in {fmt_time(self.total, fine=True)}" if self.finished else ""
                return (1.0 if self.finished else self.last), text, {"elapsed": self.total, "left": 0.0, "estimate": False, "over": False}
            done_s = sum(d for _k, _s, d in self.done)                    # what the finished stages really took
            fut_s = sum(self._predict(k, s) for k, s in self.future)       # what the stages still to come are expected to take
            over = False
            if self.cur is None:                                           # between two stages, or before the first
                total = done_s + fut_s
                frac = done_s / total if (self.done and total > 0) else 0.0
                left = fut_s if self.future else None
            else:
                c = self.cur
                el = now - c["t0"]
                f = c["frac"]
                if f is not None and f >= 0.02:                            # the stage measures its own progress
                    pc = min(f, 0.999)
                    cur_total = max(el / pc, el)                           # what it will take if it goes on at the pace it has had
                    left_c = max(cur_total - el, 0.0)
                else:                                                      # a stage that reports nothing: the time estimate
                    pred = max(c["pred"], 0.05)
                    if el <= pred:
                        pc = ON_TIME * el / pred
                        cur_total, left_c = pred, pred - el
                    else:                                                  # it takes longer than estimated: creep towards the end, do not pretend
                        pc = ON_TIME + (1.0 - ON_TIME - 0.01) * (1.0 - math.exp(-(el - pred) / (0.5 * pred)))
                        cur_total, left_c, over = el / pc, None, True
                total = done_s + cur_total + fut_s
                frac = (done_s + pc * cur_total) / max(total, 1e-9)
                left = None if left_c is None else left_c + fut_s
            frac = min(max(frac, self.last), CEILING)
            self.last = frac
            label = self.label if self.label else "Working"
            label = label[:1].upper() + label[1:]
            if self.cancelling:
                text = "Cancelling: this stops when the step that is running ends"
            else:
                text = f"{label} - {fmt_time(elapsed)} so far"
                if over:
                    text += ", taking longer than estimated"
                elif left is not None and (self.done or self.cur is not None):
                    text += f", {fmt_left(left)} left (estimate)"
            return frac, text, {"elapsed": elapsed, "left": left, "estimate": True, "over": over}


def plan_for(geom, r, mesh=None, meshing=True, solving=True):
    """[(stage, size)]: the stages that this mesh or solve is expected to go through, for the time estimate before the first one reports.
    mesh: the finished mesh when there is one in the cache (its real element and node counts are used instead of the estimates)."""
    h = r.get("h") if r else None
    if mesh is not None:
        el, nodes = float(len(mesh.get("conn", mesh.get("tets", [])))), float(len(mesh["nodes"]))
    else:
        el = estimate_for(geom, h, (r.get("mesh") or {}).get("body_h") if r else None)
        nodes = el * NODES_PER_ELEMENT
    hexdom = bool(r and (r.get("mesh") or {}).get("type") == "hexdom")
    out = []
    if mesh is None and meshing:
        out.append(("meshhex" if hexdom else "mesh", el))
    if not solving:
        return out
    unknowns = 3.0 * nodes
    bb = (geom or {}).get("bbox")
    ext = None
    if bb:
        try:
            ext = [abs(float(bb[1][i]) - float(bb[0][i])) for i in range(3)]
        except (TypeError, ValueError, IndexError):
            ext = None
    out.append(("assemble", el))
    if unknowns > DIRECT_LIMIT:
        out += [("ilu", unknowns * NNZ_PER_UNKNOWN), ("cg", unknowns)]
    else:
        out.append(("factor", factor_cost(unknowns, ext)))
    out.append(("stress", el))
    return out



# ---------------------------------------------------------------------------------------------------------------------------- the widget
def make_row():
    """The ProgressRow widget (Qt is imported here so that the arithmetic above can be used and tested without it)."""
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

    class ProgressRow(QWidget):
        """A bar and a line of text.  begin(tracker) shows it and starts following the tracker; end() fills it and hides it a few seconds later."""
        HIDE_MS = 6000

        def __init__(self):
            super().__init__()
            self.trk = None
            self.gen = 0
            lay = QVBoxLayout(self)
            lay.setContentsMargins(6, 0, 6, 6)
            lay.setSpacing(3)
            self.bar = QProgressBar()
            self.bar.setRange(0, 1000)
            self.bar.setTextVisible(True)
            self.bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bar.setFixedHeight(20)
            self.bar.setStyleSheet("QProgressBar { border: 1px solid #9fb0bd; border-radius: 6px; background: #e6edf1; color: #12333a; font-size: 11px; font-weight: bold; }"
                                   "QProgressBar::chunk { background: #0e7f86; border-radius: 5px; }")
            lay.addWidget(self.bar)
            self.lbl = QLabel("")
            self.lbl.setWordWrap(True)
            self.lbl.setStyleSheet("color:#53647c; font-size:11px;")
            lay.addWidget(self.lbl)
            self.timer = QTimer(self)
            self.timer.setInterval(120)
            self.timer.timeout.connect(self.tick)
            self.setObjectName("solve_progress")
            self.hide()

        def begin(self, trk):
            self.gen += 1
            self.trk = trk
            self.bar.setValue(0)
            self.lbl.setText("Starting...")
            self.show()
            self.timer.start()
            self.tick()

        def tick(self):
            t = self.trk
            if t is None:
                return
            frac, text, _d = t.snapshot()
            self.bar.setValue(int(round(frac * 1000)))
            self.lbl.setText(text)

        def end(self, ok):
            """The work is over: a finished one is shown full for a few seconds, a cancelled or failed one disappears (the status line says why)."""
            self.timer.stop()
            t, self.trk = self.trk, None
            if t is None:
                return
            if ok:
                self.bar.setValue(1000)
                self.lbl.setText(t.snapshot()[1])
                gen = self.gen

                def hide_later():
                    try:
                        if self.gen == gen and self.trk is None:
                            self.hide()
                    except RuntimeError:                         # the row was deleted meanwhile (the scratch window of a study case): nothing to hide
                        pass
                QTimer.singleShot(self.HIDE_MS, hide_later)
            else:
                self.hide()

        def cancelling(self):
            if self.trk is not None:
                self.trk.cancelling = True
                self.tick()

    return ProgressRow()
