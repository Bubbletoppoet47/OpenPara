"""ctl_learn.py - learn the controller gains of a self-balancing robot by trying them (no Qt).

You give the geometry (wheel, body, masses, motor limit), a target position for the base and the condition that it must not tip or touch the ground.
The learner finds the tilt and position PID gains: it starts from the linear-quadratic design for the drawing, then tries candidate gains one after another
(a CMA-ES search over the logarithms of the four gains).  Each candidate is one TRIAL: a full non-linear run of the robot with those gains.  A trial that
tips or touches the ground is a failure (the robot is reset and new gains are tried); a trial that balances is scored on how well it reached the target, how
little it leaned, how gently it used the motor, how little it overshot and how well damped the linearised loop is.  A balancing trial is also tried from the
other side and with a push, so the gains are not tuned to one lucky start.

It stops when you stop it, when the trial limit is reached, when the best gains stop improving, or when the best gains are well damped (every closed-loop
pole has a damping ratio of at least 0.95, i.e. critically damped or better, and the run overshoots the target by under 2 %).
"""
import math
import queue
import threading
import time

import numpy as np

import ctl_dyn as dyn

PARAMS = ("kp", "kd", "pkp", "pkd")
FAST_SUBSTEP = 0.0025                      # learning runs use a coarser physics step (the final answer is re-run with the normal one)
FAIL_BASE, FAIL_SPAN = 200.0, 200.0        # a failed trial costs 200..400, a balanced one never more than 100 (plus a little for poor damping)
SQUASH_AT, PASS_MAX = 60.0, 100.0          # a balanced run's cost is left alone up to 60 and squeezed smoothly toward 100 above that
SPREAD = 3.0                               # candidates stay within e^3 (about 20x) of the starting gains

DEFAULT_LEARN = dict(seed=1, robust=True, max_trials=400, stop_stagnant=True, stop_damped=True, zeta=0.95, overshoot=0.02,
                     min_trials=24, stagnant_gens=8, stagnant_tol=0.01, sigma=0.3)

STOP_TEXT = {
    "stopped": "Stopped by you.",
    "trials": "Reached the trial limit.",
    "stagnant": "The best gains stopped improving.",
    "damped": "Stopped because the best gains are well damped.",
}


def refusal(sk):
    """None if the learner can take this drawing, else one plain sentence saying why not."""
    sk = dyn.normalize(sk)
    errs, _ = dyn.check(sk)
    if errs:
        return "Fix the drawing first: " + errs[0]
    mdl = dyn.Model(sk)
    if not (mdl.root["kind"] == "wheel" and mdl.n == 2):
        return "Learning is set up for the self-balancing robot for now: one wheel with one body link on it. Draw that, or set the gains by hand."
    if not sk["controller"]["pos_on"]:
        return "Switch on 'Follow a goal position' so the robot has a target to reach."
    return None


# ------------------------------------------------------------------------------------------------------------ the search
class CMA:
    """A small (mu/mu_w, lambda) CMA-ES (Hansen): the mean and a full covariance move toward whatever scored best."""

    def __init__(self, x0, sigma, rng, lam=None):
        n = len(x0)
        self.n, self.rng, self.mean, self.sigma = n, rng, np.array(x0, float), float(sigma)
        self.lam = lam or 4 + int(3 * math.log(n))
        mu = self.lam // 2
        w = math.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
        self.mu, self.w = mu, w / w.sum()
        self.mueff = 1.0 / float(np.sum(self.w ** 2))
        m = self.mueff
        self.cc = (4 + m / n) / (n + 4 + 2 * m / n)
        self.cs = (m + 2) / (n + m + 5)
        self.c1 = 2 / ((n + 1.3) ** 2 + m)
        self.cmu = min(1 - self.c1, 2 * (m - 2 + 1 / m) / ((n + 2) ** 2 + m))
        self.damps = 1 + 2 * max(0.0, math.sqrt((m - 1) / (n + 1)) - 1) + self.cs
        self.pc, self.ps = np.zeros(n), np.zeros(n)
        self.B, self.D, self.C = np.eye(n), np.ones(n), np.eye(n)
        self.chi = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        self.gen = 0

    def ask(self):
        z = self.rng.standard_normal((self.lam, self.n))
        return self.mean + self.sigma * (self.B @ (self.D[:, None] * z.T)).T

    def tell(self, X, f):
        n = self.n
        order = np.argsort(f)[:self.mu]
        xs = np.asarray(X)[order]
        old = self.mean.copy()
        self.mean = self.w @ xs
        yw = (self.mean - old) / self.sigma
        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * (self.B @ ((self.B.T @ yw) / self.D))
        self.gen += 1
        hs = float(np.linalg.norm(self.ps) / math.sqrt(1 - (1 - self.cs) ** (2 * self.gen)) / self.chi < 1.4 + 2 / (n + 1))
        self.pc = (1 - self.cc) * self.pc + hs * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * yw
        art = (xs - old) / self.sigma
        self.C = ((1 - self.c1 - self.cmu) * self.C + self.c1 * (np.outer(self.pc, self.pc) + (1 - hs) * self.cc * (2 - self.cc) * self.C)
                  + self.cmu * (art.T * self.w) @ art)
        self.sigma *= math.exp((self.cs / self.damps) * (np.linalg.norm(self.ps) / self.chi - 1))
        self.sigma = min(self.sigma, 2.0)
        self.C = (self.C + self.C.T) / 2
        d2, self.B = np.linalg.eigh(self.C)
        self.D = np.sqrt(np.maximum(d2, 1e-20))


# ------------------------------------------------------------------------------------------------------------ what a good trial is
class Spec:
    """What the score needs to know about the problem."""

    def __init__(self, sk, mdl):
        c, r = sk["controller"], sk["run"]
        g = c["goal"]
        self.x_start = float(mdl.sense(mdl.z0(0.0))[2])
        self.travel = abs(float(g["x"]) - self.x_start)
        self.sx = max(self.travel, 0.2)
        self.tmax = mdl.tmax
        self.limit = math.radians(float(r["tilt_limit"]))
        self.m_total = float(np.sum(mdl.m))
        if g["kind"] == "ramp":
            T = float(g["t"]) + self.travel / max(abs(float(g["rate"])), 1e-6) + 3.0
        elif g["kind"] == "step":
            T = float(g["t"]) + 4.0
        else:
            T = 5.0
        self.T = min(max(T, 4.0), 20.0)
        self.T_short = min(self.T, 5.0)
        self.start_tilt = float(r["start_tilt"]) if abs(float(r["start_tilt"])) > 0.5 else 5.0


def score(res, spec):
    """(cost, parts) for one run.  Lower is better; failures are always worse than any balanced run, and a later fall is better than an earlier one."""
    T = res.duration
    if not res.ok:
        return FAIL_BASE + FAIL_SPAN * (1.0 - min(res.t_fail or 0.0, T) / T), dict(fail=True, t_fail=res.t_fail, reason=res.reason)
    t, x, goal, u, tilt = res.t, res.x, res.goal, res.u, res.tilt
    n = len(t)
    err = np.abs(x - goal) / spec.sx
    track = float(err.mean())
    last = float(err[int(0.8 * n):].mean())
    gf, d = float(goal[-1]), float(goal[-1]) - spec.x_start
    over = float(np.max((x - gf) * math.copysign(1.0, d))) / spec.sx if abs(d) > 1e-9 else 0.0
    over = max(0.0, over)
    bad = np.nonzero(err > 0.03)[0]
    settle = float(t[bad[-1]] / T) if len(bad) else 0.0
    tl = 0.3 * spec.limit
    tilt_max = float(np.max(np.abs(tilt))) / tl
    tilt_rms = float(np.sqrt(np.mean(tilt ** 2))) / tl
    ju = float(np.mean((u / spec.tmax) ** 2))
    sat = res.saturated_share()
    chat = float(np.mean(np.abs(np.diff(u)))) / spec.tmax if n > 1 else 0.0
    cost = 10 * (track + 2 * last + 1.5 * over) + 3 * settle + 2 * tilt_max ** 2 + 2 * tilt_rms + 5 * ju + 5 * sat + 20 * chat
    if cost > SQUASH_AT:                           # a chattering run that still balances must not look worse than one that fell
        cost = SQUASH_AT + (PASS_MAX - SQUASH_AT) * (1.0 - math.exp(-(cost - SQUASH_AT) / (PASS_MAX - SQUASH_AT)))
    return cost, dict(fail=False, track=track, last=last, over=over, settle=settle, tilt_max=math.degrees(float(np.max(np.abs(tilt)))),
                      effort=float(np.max(np.abs(u))) / spec.tmax, sat=sat, chatter=chat)


class Trial:
    """One candidate's evaluation.  `res` is its nominal run (what the screen replays)."""

    def __init__(self, index, gen, gains):
        self.index, self.gen, self.gains = index, gen, gains
        self.cost = float("inf")
        self.ok = False
        self.res = None
        self.parts = {}
        self.zeta = -1.0
        self.scen = []
        self.is_best = False
        self.seconds = 0.0

    def line(self, best=None):
        if not self.ok:
            what = "fell over" if self.parts.get("reason") == "tilt" else "hit the ground"
            return "Trial %d: %s after %.1f s" % (self.index, what, self.parts.get("t_fail") or 0.0)
        bad = [name for name, ok in self.scen if not ok]
        base = "Trial %d: balanced, score %.2f" % (self.index, self.cost)
        if bad:
            return base + " (but it %s)" % " and ".join("fell when " + b for b in bad)
        return base + (" - best so far" if self.is_best else (" (best %.2f)" % best.cost if best is not None else ""))


class Learner:
    """Steps through trials one at a time: step() runs one and returns it; stop_reason says why it ended (None while it can go on)."""

    def __init__(self, sk, settings=None, start=None):
        self.sk = dyn.normalize(sk)
        why = refusal(self.sk)
        if why:
            raise dyn.SketchError(why)
        self.set = dict(DEFAULT_LEARN)
        self.set.update(settings or {})
        self.mdl = dyn.Model(self.sk)
        self.spec = Spec(self.sk, self.mdl)
        g = start
        if g is None:
            try:
                g = dyn.suggest_gains(self.sk)
            except dyn.SketchError:
                g = {k: self.sk["controller"][k] for k in PARAMS}
        self.start = {k: max(abs(float(g[k])), 1e-4) for k in PARAMS}
        self.x0 = np.log([self.start[k] for k in PARAMS])
        self.rng = np.random.default_rng(int(self.set["seed"]))
        self.cma = CMA(self.x0, self.set["sigma"], self.rng)
        self.history, self.best, self.stop_reason = [], None, None
        self.pending, self.gen_x, self.gen_f = [], [], []
        self.gen_best = []                                      # the best cost at the end of each generation
        self.limit = int(self.set["max_trials"])
        self.scenarios = self._scenarios()

    # ------------------------------------------------------------------ one trial
    def _controller(self, gains):
        c = dict(self.sk["controller"])
        c.update(gains)
        c.update(ki=0.0, pki=0.0, pos_on=True)
        return c

    def _sketch(self, gains, duration, start_tilt, push=None):
        sk = dyn.normalize(self.sk)
        sk["controller"] = dict(self._controller(gains), goal=dict(self.sk["controller"]["goal"]))
        sk["run"].update(duration=duration, start_tilt=start_tilt)
        sk["run"]["push"] = dict(on=False, force=0.0, t=0.0, dur=0.1) if push is None else dict(on=True, **push)
        return sk

    def _scenarios(self):
        sp = self.spec
        out = [("nominal", dict(duration=sp.T, start_tilt=sp.start_tilt, push=None), 0.6)]
        if self.set["robust"]:
            out.append(("it started leaning the other way", dict(duration=sp.T_short, start_tilt=-1.2 * sp.start_tilt, push=None), 0.2))
            out.append(("it was pushed", dict(duration=sp.T_short, start_tilt=sp.start_tilt, push=dict(force=0.15 * sp.m_total * dyn.G, t=1.5, dur=0.1)), 0.2))
        return out

    def evaluate(self, x, index, gen):
        t0 = time.time()
        x = np.clip(x, self.x0 - SPREAD, self.x0 + SPREAD)
        gains = {k: float(v) for k, v in zip(PARAMS, np.exp(x))}
        tr = Trial(index, gen, gains)
        total = 0.0
        for k, (name, run, weight) in enumerate(self.scenarios):
            res = dyn.simulate(self._sketch(gains, **run), mdl=self.mdl, substep=FAST_SUBSTEP)
            c, parts = score(res, self.spec)
            if k == 0:
                tr.res, tr.parts, tr.ok = res, parts, res.ok
                if not res.ok:
                    tr.cost = c
                    break
            tr.scen.append((name, res.ok))
            total += weight * c
        else:
            try:
                tr.zeta = dyn.min_damping(self.mdl.closed_loop_poles(self._controller(gains)))
            except Exception:                              # noqa: BLE001 - a singular linearisation just scores as undamped
                tr.zeta = -1.0
            tr.cost = total + 6.0 * max(0.0, float(self.set["zeta"]) - tr.zeta)
        tr.seconds = time.time() - t0
        return tr

    # ------------------------------------------------------------------ the loop
    def step(self):
        if self.stop_reason:
            return None
        if not self.pending:
            X = np.clip(self.cma.ask(), self.x0 - SPREAD, self.x0 + SPREAD)
            if self.cma.gen == 0:
                X[0] = self.x0                                           # the very first trial is the starting design itself
            self.pending, self.gen_x, self.gen_f = list(X), [], []
        x = self.pending.pop(0)
        tr = self.evaluate(x, len(self.history) + 1, self.cma.gen + 1)
        self.history.append(tr)
        self.gen_x.append(np.clip(x, self.x0 - SPREAD, self.x0 + SPREAD))
        self.gen_f.append(tr.cost)
        if self.best is None or tr.cost < self.best.cost:
            if self.best is not None:
                self.best.is_best = False
            tr.is_best = True
            self.best = tr
        if not self.pending:
            self.cma.tell(self.gen_x, self.gen_f)
            self.gen_best.append(self.best.cost)
            self.stop_reason = self.stop_reason or self._why_stop()      # a stop pressed during this trial stays "stopped"
        elif len(self.history) >= self.limit:
            self.stop_reason = self.stop_reason or "trials"
        return tr

    def _why_stop(self):
        s, b, n = self.set, self.best, len(self.history)
        if n >= self.limit:
            return "trials"
        if s["stop_damped"] and n >= s["min_trials"] and b.ok and b.cost < FAIL_BASE and all(ok for _, ok in b.scen) \
                and b.zeta >= s["zeta"] and b.parts.get("over", 1.0) <= s["overshoot"]:
            return "damped"
        k = int(s["stagnant_gens"])
        if s["stop_stagnant"] and len(self.gen_best) > k and b.cost < FAIL_BASE:
            if self.gen_best[-k - 1] - self.gen_best[-1] < s["stagnant_tol"] * abs(self.gen_best[-1]):
                return "stagnant"
        return None

    def stop(self):
        if self.stop_reason is None:
            self.stop_reason = "stopped"

    def resume(self, more=200):
        """Carry on after a stop: more trials, same search state."""
        self.stop_reason = None
        self.limit = len(self.history) + int(more)

    def run(self, on_trial=None, stop=None):
        while self.stop_reason is None:
            if stop and stop():
                self.stop()
                break
            tr = self.step()
            if tr is not None and on_trial:
                on_trial(tr)
        return self.best

    # ------------------------------------------------------------------ the answer
    def best_gains(self):
        return dict(self.best.gains) if self.best is not None else None

    def verify(self):
        """The best gains re-run with the normal (finer) physics step: this is the run the section shows as the answer."""
        if self.best is None:
            return None
        sk = self._sketch(self.best.gains, self.spec.T, self.spec.start_tilt)
        return dyn.simulate(sk, mdl=self.mdl)

    def summary(self):
        """A few plain sentences about the learning so far."""
        n, b = len(self.history), self.best
        ok = sum(1 for t in self.history if t.ok)
        out = ["%d trials: %d balanced, %d fell or hit the ground." % (n, ok, n - ok)]
        if b is None or not b.ok:
            out.append("None balanced yet.")
        else:
            p = b.parts
            out.append("Best gains: balanced, reached the target%s, never leaned more than %.1f°, used at most %.0f %% of the motor." %
                       (" and settled in about %.1f s" % (p["settle"] * self.spec.T) if p["settle"] < 0.97 else "", p["tilt_max"], 100 * p["effort"]))
            out.append("Overshoot of the target %.1f %%. %s" % (100 * p["over"], damping_words(b.zeta)))
            bad = [name for name, ok in b.scen if not ok and name != "nominal"]
            if bad:
                out.append("It is not robust yet: it fell when %s." % " and when ".join(bad))
            elif len(b.scen) > 1:
                out.append("It also recovers when it starts leaning the other way and when it is pushed.")
        if self.stop_reason:
            out.append(STOP_TEXT[self.stop_reason] if self.stop_reason != "trials" else "Reached the limit of %d trials." % self.limit)
        return " ".join(out)


def damping_words(zeta):
    if zeta >= 0.95:
        return "The loop is critically damped or better: every pole is real or nearly so, so there is no ringing."
    if zeta > 0:
        return "The least damped part of the loop has damping ratio %.2f (1 would be critical damping), so there is a little ringing." % zeta
    return "The linearised loop is not stable."


# ------------------------------------------------------------------------------------------------------------ in the background
class Worker(threading.Thread):
    """Runs a Learner on its own thread.  Trials arrive on `out` (a queue); the end is ("done", None) - with `final` holding the verified best run - or ("error", exception).
    In live mode the worker waits after each trial until release() is called (the screen has finished showing it)."""

    def __init__(self, learner):
        super().__init__(daemon=True)
        self.learner = learner
        self.out = queue.Queue()
        self.stop_ev = threading.Event()
        self.gate = threading.Event()
        self.live = False
        self.final = None                                               # the best gains re-run with the fine physics step, ready when "done" arrives

    def run(self):
        try:
            while not self.stop_ev.is_set() and self.learner.stop_reason is None:
                tr = self.learner.step()
                if tr is None:
                    break
                self.gate.clear()
                self.out.put(tr)
                if self.live:
                    while self.live and not self.stop_ev.is_set() and not self.gate.wait(0.05):
                        pass
            if self.learner.best is not None and self.learner.best.ok:
                self.final = self.learner.verify()                      # about a second of work: done here so the screen never waits for it
            self.out.put(("done", None))
        except Exception as e:                                          # noqa: BLE001 - reported on the screen, not lost with the thread
            self.out.put(("error", e))

    def release(self):
        self.gate.set()

    def stop(self):
        self.stop_ev.set()
        self.learner.stop()
        self.gate.set()
