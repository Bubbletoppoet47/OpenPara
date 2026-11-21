"""The gain learner (dev_addons/controls/ctl_learn.py, no Qt): the search, the score, the stop conditions, different robots, the background worker."""
import copy
import math
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "controls"), os.path.join(HERE, "shared"), HERE]
import numpy as np

import ctl_dyn as d
import ctl_learn as L


def robot(**kw):
    sk = d.example_robot()
    w, b, m = sk["parts"]
    if "r" in kw:
        w["r"] = kw["r"]
    if "wm" in kw:
        w["m"] = kw["wm"]
    if "L" in kw:
        b["length"] = kw["L"]
        m["at"] = 0.83 * kw["L"]
    if "bm" in kw:
        b["m"] = kw["bm"]
    if "mm" in kw:
        m["m"] = kw["mm"]
    if "tmax" in kw:
        b["motor"]["max"] = kw["tmax"]
    if "goal" in kw:
        sk["controller"]["goal"]["x"] = kw["goal"]
    return sk


# ---- the search itself: CMA-ES finds the bottom of a stretched, tilted bowl ------------------------------------------------------------------------
rng = np.random.default_rng(3)
A = np.array([[4.0, 1.5, 0, 0], [1.5, 1.0, 0, 0], [0, 0, 0.3, 0.1], [0, 0, 0.1, 0.2]])
target = np.array([1.0, -0.5, 0.7, 0.2])
cma = L.CMA(np.zeros(4), 0.5, rng)
assert cma.lam == 8
for _ in range(120):
    X = cma.ask()
    cma.tell(X, [float((x - target) @ A @ (x - target)) for x in X])
assert np.linalg.norm(cma.mean - target) < 1e-2, cma.mean
r2 = np.random.default_rng(3)
c2 = L.CMA(np.zeros(4), 0.5, r2)
X1 = c2.ask()
assert np.allclose(X1, L.CMA(np.zeros(4), 0.5, np.random.default_rng(3)).ask())            # same seed, same candidates

# ---- damping ratios -------------------------------------------------------------------------------------------------------------------------
assert d.min_damping(np.array([-1.0 + 0j, -4.0 + 0j])) == 1.0
assert abs(d.min_damping(np.array([-1 + 1j, -1 - 1j])) - math.sqrt(0.5)) < 1e-12
assert d.min_damping(np.array([0 + 2j, 0 - 2j])) == 0.0
assert d.min_damping(np.array([1.0 + 0j, -3.0 + 0j])) < 0
assert d.min_damping(np.array([-1 + 0j, -1 + 1e-9j])) == 1.0                                # a pole pair that is really double and real
mdl = d.Model(robot())
g = d.suggest_gains(robot())
poles = mdl.closed_loop_poles(dict(robot()["controller"], **g))
assert max(p.real for p in poles) < 0                                                       # the LQR start is a stable loop
assert 0.5 < d.min_damping(poles) <= 1.0
bad = dict(robot()["controller"], kp=0.01, kd=0.0, pkp=0.0, pkd=0.0)
assert d.min_damping(mdl.closed_loop_poles(bad)) < 0                                        # no control on an inverted pendulum: unstable

# ---- the score: any failure is worse than any balanced run, and a later fall is better than an earlier one ------------------------------------------
sk = robot()
lr = L.Learner(sk)
sp = lr.spec
good = lr.evaluate(np.log([lr.start[k] for k in L.PARAMS]), 1, 1)
assert good.ok and good.cost < 100 and all(ok for _, ok in good.scen)
fell_early = lr.evaluate(np.log([lr.start["kp"] * 20, lr.start["kd"], lr.start["pkp"], lr.start["pkd"]]), 2, 1)       # stiff, with no extra damping
assert not fell_early.ok and L.FAIL_BASE <= fell_early.cost <= L.FAIL_BASE + L.FAIL_SPAN
assert fell_early.cost > good.cost
assert fell_early.line().startswith("Trial 2: ") and ("fell over" in fell_early.line() or "hit the ground" in fell_early.line())
assert "balanced" in good.line()
r_early = d.simulate(lr._sketch(dict(kp=0.0, kd=0.0, pkp=0.0, pkd=0.0), 6.0, 5.0), mdl=lr.mdl, substep=L.FAST_SUBSTEP)
assert not r_early.ok
c_early, _ = L.score(r_early, sp)
r_late = copy.copy(r_early)
r_late.t_fail = r_early.t_fail + 0.5
c_late, _ = L.score(r_late, sp)
assert c_late < c_early                                                                       # surviving longer is progress even while failing
chatter = lr.evaluate(np.log([lr.start["kp"], lr.start["kd"] * 20, lr.start["pkp"], lr.start["pkd"]]), 4, 1)               # balances, but the motor buzzes
assert chatter.ok and good.cost < chatter.cost < L.FAIL_BASE, chatter.cost
assert L.score(r_early, sp)[0] > chatter.cost
calm = lr.evaluate(np.log([lr.start[k] for k in L.PARAMS]), 3, 1)
assert calm.cost == good.cost                                                                # an evaluation is reproducible

# ---- learning: the first trial is the starting design, and the best never gets worse ---------------------------------------------------------------
lr = L.Learner(robot(), dict(max_trials=64, stop_damped=False, stop_stagnant=False))
seen = []
lr.run(on_trial=seen.append)
assert len(seen) == 64 and lr.stop_reason == "trials"
assert all(abs(seen[0].gains[k] / lr.start[k] - 1) < 1e-12 for k in L.PARAMS)
costs = [t.cost for t in seen]
bests = np.minimum.accumulate(costs)
assert lr.best.cost == bests[-1] <= costs[0]
assert sum(t.is_best for t in seen) == 1 and lr.best.is_best
assert all(t.index == i + 1 for i, t in enumerate(seen))
assert lr.best.cost < costs[0] - 0.5, (costs[0], lr.best.cost)                               # it really improved on the starting design
assert "64 trials" in lr.summary() and "limit" in lr.summary()
# the answer is re-run with the normal physics step and still balances
v = lr.verify()
assert v.ok and v.max_tilt_deg() < 20 and abs(v.final_error()) < 0.1
bg = lr.best_gains()
assert set(bg) == set(L.PARAMS) and all(x > 0 for x in bg.values())

# ---- same seed, same answer; another seed, another path ----------------------------------------------------------------------------------------
a = L.Learner(robot(), dict(max_trials=16)); a.run()
b = L.Learner(robot(), dict(max_trials=16)); b.run()
assert [t.cost for t in a.history] == [t.cost for t in b.history]
c = L.Learner(robot(), dict(max_trials=16, seed=2)); c.run()
assert [t.cost for t in a.history][1:] != [t.cost for t in c.history][1:]

# ---- stop conditions --------------------------------------------------------------------------------------------------------------------------------
lr = L.Learner(robot())
lr.run(stop=lambda: len(lr.history) >= 5)                                                    # the user presses Stop after a few trials
assert lr.stop_reason == "stopped" and len(lr.history) == 5 and lr.best is not None
lr.resume(more=8)                                                                            # Continue picks up where it left off, same search
k = len(lr.history)
lr.run()
assert lr.stop_reason in ("trials", "damped", "stagnant") and len(lr.history) > k
assert lr.history[-1].index == len(lr.history)

lr = L.Learner(robot())                                                                      # default: stops once critically damped
lr.run()
assert lr.stop_reason == "damped", lr.stop_reason
b = lr.best
assert b.ok and b.zeta >= 0.95 and b.parts["over"] <= 0.02 and all(ok for _, ok in b.scen) and len(lr.history) >= lr.set["min_trials"]
assert "critically damped" in lr.summary()

lr = L.Learner(robot(), dict(stop_damped=False, stagnant_gens=4, stagnant_tol=0.5))          # a coarse "no further improvement" test fires
lr.run()
assert lr.stop_reason == "stagnant", lr.stop_reason

lr = L.Learner(robot(), dict(stop_damped=False, stop_stagnant=False, max_trials=10))
lr.run()
assert lr.stop_reason == "trials" and len(lr.history) == 10

# a stop pressed in the middle of a trial stays a stop (it is not overwritten when the generation ends)
lr = L.Learner(robot(), dict(max_trials=400))
orig = lr.evaluate


def ev(x, i, g):
    tr = orig(x, i, g)
    if i == lr.cma.lam:                                                                       # Stop arrives during the last trial of the generation
        lr.stop()
    return tr


lr.evaluate = ev
lr.run()
assert lr.stop_reason == "stopped" and len(lr.history) == lr.cma.lam

# ---- different robots: all of them are learned -------------------------------------------------------------------------------------------------------
for name, kw in (("short", dict(L=0.15)), ("big wheel", dict(r=0.1, wm=0.3)), ("weak motor", dict(tmax=0.3)), ("far goal", dict(goal=3.0))):
    lr = L.Learner(robot(**kw), dict(max_trials=100))
    lr.run()
    v = lr.verify()
    assert lr.best.ok and v.ok, (name, lr.summary())
    assert lr.best.cost < 100 and all(ok for _, ok in lr.best.scen), name
    assert lr.best.zeta > 0.5, (name, lr.best.zeta)
    assert abs(v.goal[-1] - kw.get("goal", 1.0)) < 1e-6

# the geometry is never changed by the learner
sk0 = robot(L=0.6)
snap = copy.deepcopy(sk0)
L.Learner(sk0, dict(max_trials=12)).run()
assert sk0 == snap

# ---- starting from poor gains the learner still ends up balancing ------------------------------------------------------------------------------------
sk = robot()
g0 = d.suggest_gains(sk)
lr = L.Learner(sk, start={k: v * 4.0 for k, v in g0.items()}, settings=dict(max_trials=80))
lr.run()
assert lr.verify().ok and lr.best.cost < 100
# a start that falls over on the first trial: the failures are reported, then it finds gains that hold
weak = {k: v * 0.02 for k, v in g0.items()}
lr = L.Learner(sk, start=weak, settings=dict(max_trials=200))
lr.run()
assert not lr.history[0].ok
assert lr.best.ok, lr.summary()

# ---- refusals in plain words ------------------------------------------------------------------------------------------------------------------------
cp = d.example_cartpole()
assert "self-balancing robot" in L.refusal(cp)
try:
    L.Learner(cp)
    raise AssertionError("a cart and pole is not learned yet")
except d.SketchError as e:
    assert "self-balancing robot" in str(e)
nopos = robot()
nopos["controller"]["pos_on"] = False
assert "goal position" in L.refusal(nopos)
assert "Fix the drawing" in L.refusal(dict(parts=[dict(id="p", kind="pivot", x=0, y=1)], controller={}))
assert L.refusal(robot()) is None

# ---- in the background: a worker thread hands trials over without touching the screen -------------------------------------------------------------------
lr = L.Learner(robot(), dict(max_trials=12, stop_damped=False, stop_stagnant=False))
w = L.Worker(lr)
w.start()
got = []
while True:
    item = w.out.get(timeout=60)
    if isinstance(item, tuple):
        assert item == ("done", None)
        break
    got.append(item)
w.join(5)
assert len(got) == 12 and not w.is_alive() and lr.stop_reason == "trials"

# live mode: the worker waits for release() after every trial, so the queue never runs ahead of the screen
lr = L.Learner(robot(), dict(max_trials=6, stop_damped=False, stop_stagnant=False))
w = L.Worker(lr)
w.live = True
w.start()
first = w.out.get(timeout=60)
time.sleep(0.6)
assert w.out.empty() and len(lr.history) == 1                                                  # waiting for the screen, not computing on
w.release()
second = w.out.get(timeout=60)
assert second.index == 2
w.live = False                                                                                  # flipping to background mode lets it run free
rest = []
while True:
    item = w.out.get(timeout=60)
    if isinstance(item, tuple):
        break
    rest.append(item)
assert len(rest) == 4 and lr.stop_reason == "trials"
w.join(5)

# stop while it is waiting in live mode: it ends promptly and keeps its best
lr = L.Learner(robot(), dict(max_trials=50))
w = L.Worker(lr)
w.live = True
w.start()
w.out.get(timeout=60)
w.stop()
end = w.out.get(timeout=10)
assert end == ("done", None)
w.join(5)
assert not w.is_alive() and lr.stop_reason == "stopped" and lr.best is not None

# an error inside the worker comes back as a message, not a dead thread
lr = L.Learner(robot(), dict(max_trials=5))
lr.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
w = L.Worker(lr)
w.start()
kind, exc = w.out.get(timeout=10)
assert kind == "error" and "boom" in str(exc)
w.join(5)

# the main thread stays free while the worker computes (it can keep counting)
lr = L.Learner(robot(), dict(max_trials=24, stop_damped=False, stop_stagnant=False))
w = L.Worker(lr)
t0 = time.time()
w.start()
ticks = 0
while w.is_alive() and time.time() - t0 < 60:
    time.sleep(0.01)
    ticks += 1
assert ticks > 20, ticks

print("PASS controls learn")
