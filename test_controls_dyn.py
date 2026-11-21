"""Dynamic simulation engine (dev_addons/controls/ctl_dyn.py, no Qt): physics against known answers, the controller, plain-word checks, files."""
import copy
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "controls"), os.path.join(HERE, "shared"), HERE]
import numpy as np

import ctl_dyn as d


def free_model(sk):
    return d.Model(sk, _checked=True)


def run_free(m, z, T, h=1e-3, u=0.0):
    for _ in range(int(round(T / h))):
        z = m.step(z, u, 0.0, h)
    return z


# ---- a pendulum swings with the textbook period -----------------------------------------------------------------------------------------
pend = dict(parts=[dict(id="p", kind="pivot", x=0, y=1.5), dict(id="r", kind="link", parent="p", length=1.0, m=0.0, angle=-90.0),
                   dict(id="b", kind="mass", parent="r", at=1.0, m=1.0)], controller=dict(balance="r"))
m = free_model(pend)
z, t, h, cross = m.z0(5.0), 0.0, 1e-3, []
for _ in range(12000):
    zn = m.step(z, 0.0, 0.0, h)
    a0, a1 = z[0] + math.pi / 2, zn[0] + math.pi / 2
    if a0 > 0 >= a1:
        cross.append(t + h * a0 / (a0 - a1))
    z, t = zn, t + h
period = float(np.mean(np.diff(cross)))
expect = 2 * math.pi * math.sqrt(1.0 / d.G) * (1 + math.radians(5) ** 2 / 16)           # small-amplitude series
assert abs(period - expect) / expect < 1e-5, (period, expect)

# ---- a physical pendulum with a rod: I = m L^2 / 3 about the pin ----------------------------------------------------------------------------
rod = dict(parts=[dict(id="p", kind="pivot", x=0, y=1.5), dict(id="r", kind="link", parent="p", length=0.8, m=2.0, angle=-90.0)], controller=dict(balance="r"))
A, B = free_model(rod).linear()
w2 = 1.5 * d.G / 0.8                                                                  # m g (L/2) / (m L^2/3)
assert abs(A[1, 0] + w2) < 1e-5 * w2, (A, w2)

# ---- a joint spring and damper act on the relative angle, resting at the drawn pose -----------------------------------------------------------------
spr = dict(parts=[dict(id="p", kind="pivot", x=0, y=1.5), dict(id="r", kind="link", parent="p", length=0.8, m=2.0, angle=-90.0, k=2.0, c=0.3)],
           controller=dict(balance="r"))
ms = free_model(spr)
A, B = ms.linear()
Ipin = 2.0 * 0.8 ** 2 / 3
assert abs(A[1, 0] + (2.0 + 2.0 * d.G * 0.4) / Ipin) < 1e-5 * (2.0 + 2.0 * d.G * 0.4) / Ipin       # w^2 = (k + m g L/2) / I
assert abs(A[1, 1] + 0.3 / Ipin) < 1e-5 / Ipin                                                       # damping rate = c / I
z = ms.z0(10.0)
E0 = ms.energy(z)
z1 = ms.step(z, 0.0, 0.0, 1e-3)
assert ms.energy(z1) <= E0 + 1e-12                                                                    # the damper only takes energy out
nodamp = dict(parts=[dict(spr["parts"][0]), dict(spr["parts"][1], c=0.0)], controller=spr["controller"])
mn = free_model(nodamp)
z = mn.z0(10.0)
E0, drift = mn.energy(z), 0.0
for _ in range(3000):
    z = mn.step(z, 0.0, 0.0, 1e-3)
    drift = max(drift, abs(mn.energy(z) - E0))
assert drift < 1e-6 * abs(E0 + 50), drift                                                             # spring + gravity + motion conserve energy

# ---- a double pendulum conserves energy ----------------------------------------------------------------------------------------------------
dbl = dict(parts=[dict(id="p", kind="pivot", x=0, y=2.0), dict(id="a", kind="link", parent="p", length=0.7, m=1.0, angle=-30.0),
                  dict(id="b", kind="link", parent="a", at=0.7, length=0.5, m=0.6, angle=10.0), dict(id="mm", kind="mass", parent="b", at=0.5, m=0.2)],
           controller=dict(balance="a"))
m2 = free_model(dbl)
z = m2.z0(0.0)
E0 = m2.energy(z)
drift = 0.0
for _ in range(5000):
    z = m2.step(z, 0.0, 0.0, 1e-3)
    drift = max(drift, abs(m2.energy(z) - E0))
assert drift < 1e-6 * abs(E0), drift
# the mass matrix is symmetric and positive definite everywhere along the swing
Mm = m2.mass_matrix(z[:2])
assert np.allclose(Mm, Mm.T) and np.linalg.eigvalsh(Mm).min() > 0

# ---- the cart-pole linearises to the known matrices -----------------------------------------------------------------------------------------
M_, mb, L = 1.0, 0.1, 0.5
cp = dict(parts=[dict(id="c", kind="cart", m=M_, w=0.3, h=0.1, motor=dict(max=20)), dict(id="pole", kind="link", parent="c", length=L, m=0.0, angle=90),
                 dict(id="bob", kind="mass", parent="pole", at=L, m=mb)], controller=dict(balance="pole"))
mc = free_model(cp)
A, B = mc.linear()
C = mc.sense_matrix()                                          # rows: tilt, tilt rate, x, speed over z = [x, angle, x', angle']
T = np.array([C[2], C[0], C[3], C[1]])                           # to [x, tilt, v, tilt rate]
At, Bt = T @ A @ np.linalg.inv(T), T @ B
g = d.G
want_A = np.array([[0, 0, 1, 0], [0, 0, 0, 1], [0, -mb * g / M_, 0, 0], [0, (M_ + mb) * g / (M_ * L), 0, 0]])
want_B = np.array([[0], [0], [1 / M_], [-1 / (M_ * L)]])
assert np.allclose(At, want_A, atol=1e-5) and np.allclose(Bt, want_B, atol=1e-5), (At, Bt)
ev = np.sort(np.linalg.eigvals(A).real)
assert abs(ev[-1] - math.sqrt((M_ + mb) * g / (M_ * L))) < 1e-6 and abs(ev[0] + ev[-1]) < 1e-6
tf = d.plant_tf(cp)                                              # G(s) = -1/(M L) / (s^2 - (M+m) g /(M L))
assert tf["unstable"] and len(tf["den"]) == 3 and abs(tf["num"][0] + 1 / (M_ * L)) < 1e-6 and abs(tf["den"][2] + (M_ + mb) * g / (M_ * L)) < 1e-5
tfx = d.plant_tf(cp, "x")                                        # a right-half-plane zero: moving sideways means leaning the wrong way first
assert any(zr.real > 1e-6 for zr in tfx["zeros"])

# ---- a rolling wheel: no slipping, a = -tau / (1.5 m r) ------------------------------------------------------------------------------------------
wh = dict(parts=[dict(id="w", kind="wheel", r=0.1, m=2.0, motor=dict(max=5)), dict(id="l", kind="link", parent="w", length=0.2, m=1e-9, angle=90)],
          controller=dict(balance="l"))
mw = free_model(wh)
acc = mw.deriv(mw.z0(0), 1.0)
assert abs(0.1 * acc[2] - (-1.0 / (1.5 * 2.0 * 0.1))) < 1e-6
z = run_free(mw, mw.z0(0), 1.0, u=0.5)                           # constant torque from rest: x = v t / 2, x = r psi (no slip)
assert abs(mw.sense(z)[2] - 0.1 * z[0]) < 1e-12 and abs(mw.sense(z)[2] - 0.5 * (-0.5 / (1.5 * 2.0 * 0.1)) * 1.0) < 1e-6

# ---- the sketch is checked in plain words ---------------------------------------------------------------------------------------------------
def errs(sk):
    return d.check(sk)[0]


assert d.check(d.example_robot()) == ([], [])
assert any("stand on" in e for e in errs(dict(parts=[])))
sk = d.example_robot()
sk["parts"].append(dict(id="c2", kind="cart"))
assert any("2 bases" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["parent"] = None
assert any("not attached" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["motor"] = None
assert any("Nothing drives" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][0]["motor"] = dict(max=1)
assert any("one motor" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][2]["at"] = 0.5
assert any("only 0.3 m long" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["m"] = sk["parts"][2]["m"] = 0.0
assert any("no mass" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["angle"] = 70.0
e, w = d.check(sk)
assert not e and any("not in balance" in x for x in w)
sk = d.example_pendulum_up()
sk["parts"][0]["y"] = 0.0
sk["parts"][1]["angle"] = -90.0
assert any("below the ground" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["parent"] = "battery"
assert any("cannot be attached to a mass" in e for e in errs(sk))
sk = d.example_robot()
sk["parts"][1]["parent"] = "body"
assert errs(sk)                                                   # a link cannot be its own parent
try:
    d.simulate(dict(parts=[]))
    raise AssertionError("simulate must refuse a bad drawing")
except d.SketchError as e:
    assert "stand on" in str(e)

# ---- unfinished drawings can still be drawn (the orphan is flagged, nothing raises) ------------------------------------------------------------
sk = d.example_robot()
sk["parts"][1]["parent"] = None
sh = d.layout(sk)
assert [s["ok"] for s in sh if s["kind"] == "link"] == [False] and [s["ok"] for s in sh if s["kind"] == "mass"] == [False]
assert d.layout(dict(parts=[])) == []

# ---- adding and removing parts from the editor -----------------------------------------------------------------------------------------------
sk = d.normalize(dict(parts=[]))
w = d.add_part(sk, "wheel")
l1 = d.add_part(sk, "link", w)
l2 = d.add_part(sk, "link", l1)
mm = d.add_part(sk, "mass", l1)
assert d.part(sk, l2)["at"] == d.part(sk, l1)["length"] and d.part(sk, mm)["parent"] == l1 and d.part(sk, l1)["parent"] == w
assert d.part(sk, d.add_part(sk, "mass", w))["parent"] is None                  # a mass can only sit on a link
assert {p["id"] for p in sk["parts"]} == {w, l1, l2, mm, "mass2"}
gone = d.remove_part(sk, l1)
assert gone == {l1, l2, mm} and [p["id"] for p in sk["parts"]] == [w, "mass2"]
assert d.normalize(json.loads(json.dumps(d.example_robot()))) == d.example_robot()      # survives a trip through the file

# ---- the controller stands each example up --------------------------------------------------------------------------------------------------
for name, fn in d.EXAMPLES:
    sk = fn()
    assert d.check(sk) == ([], []), name
    r = d.simulate(sk)
    assert r.ok and r.n > 100, (name, r.summary())
    assert abs(r.t[-1] - sk["run"]["duration"]) < 1e-9
    assert np.all(np.isfinite(r.z))
r = d.simulate(d.example_robot())
assert r.max_tilt_deg() < 5.2 and abs(r.final_error()) < 0.02 and np.max(np.abs(r.u)) <= 1.0 + 1e-12
assert abs(r.x[-1] - 1.0) < 0.02 and "Held its balance" in r.summary()
# the goal is followed: a ramp moves at its rate, a step jumps, a fixed point is held from the start
sk = d.example_robot()
sk["controller"]["goal"].update(kind="ramp", x=0.5, rate=0.1, t=2.0)
assert abs(d.goal_at(sk["controller"], 1.0, 0.0)) < 1e-12 and abs(d.goal_at(sk["controller"], 4.0, 0.0) - 0.2) < 1e-12 and d.goal_at(sk["controller"], 99.0, 0.0) == 0.5
sk["controller"]["goal"]["kind"] = "step"
assert d.goal_at(sk["controller"], 1.9, 0.0) == 0.0 and d.goal_at(sk["controller"], 2.0, 0.0) == 0.5
sk["controller"]["goal"]["kind"] = "hold"
assert d.goal_at(sk["controller"], 0.0, 0.0) == 0.5
r = d.simulate(sk)
assert r.ok and abs(r.x[-1] - 0.5) < 0.02
# the torque direction is found by itself, and the controller works from the linear model's own sign
for name, fn in d.EXAMPLES:
    sk = fn()
    assert d.Model(sk).polarity(sk["controller"]) == d.suggest_gains(sk)["polarity"]
# flip the motor's sense (a motor wired the other way round): the auto direction flips with it and the robot still stands
sk = d.example_robot()
mdl = d.Model(sk)
p0 = mdl.polarity(sk["controller"])
mdl.Qm = -mdl.Qm
mdl._lin = mdl._pol = None
assert mdl.polarity(sk["controller"]) == -p0

# ---- falling is detected and reported -----------------------------------------------------------------------------------------------------------------
sk = d.example_robot()
sk["controller"].update(kp=0, kd=0, pkp=0, pkd=0)
r = d.simulate(sk)
assert not r.ok and r.reason == "tilt" and 0.1 < r.t_fail < 1.0 and "Fell over" in r.summary() and r.n < sk["run"]["duration"] * 200
sk = d.example_robot()
sk["controller"].update(kp=0, kd=0, pkp=0, pkd=0)
sk["run"]["tilt_limit"] = 175.0                                                # let it fall right over: the body hits the ground
sk["run"]["duration"] = 3.0
r = d.simulate(sk)
assert not r.ok and r.reason == "ground" and "Hit the ground" in r.summary()
# a weak motor saturates and the summary says so
sk = d.example_robot()
sk["parts"][1]["motor"]["max"] = 0.12
r = d.simulate(sk)
assert (not r.ok) or r.saturated_share() > 0
# a push on the tip is survived (and is felt)
sk = d.example_robot()
sk["run"]["push"].update(on=True, force=1.0, t=5.0, dur=0.1)
r2 = d.simulate(sk)
assert r2.ok and np.max(np.abs(r2.u[1000:1200])) > np.max(np.abs(d.simulate(d.example_robot()).u[1000:1200]))

# ---- design numbers change the answer the way physics says -------------------------------------------------------------------------------------
fast = d.example_robot()
tall = d.example_robot()
tall["parts"][1]["length"] = 0.6
tall["parts"][2]["at"] = 0.55
pf, pt = d.plant_tf(fast)["poles"], d.plant_tf(tall)["poles"]
assert max(p.real for p in pt) < max(p.real for p in pf)                       # a taller body falls more slowly (smaller unstable pole)

# ---- gains come out of an LQR design and map exactly onto the cascade -------------------------------------------------------------------------------
sk = d.example_robot()
gs = d.suggest_gains(sk)
assert gs["kp"] > 0 and gs["kd"] > 0 and gs["pkp"] > 0 and gs["pkd"] > 0
try:
    d.suggest_gains(dict(parts=[dict(id="p", kind="pivot", x=0, y=2.0), dict(id="a", kind="link", parent="p", length=0.7, m=1.0, angle=90.0, motor=dict(max=5)),
                                dict(id="b", kind="link", parent="a", at=0.7, length=0.5, m=0.6, angle=90.0)], controller=dict(balance="a")))
    raise AssertionError("two joints cannot be tuned")
except d.SketchError as e:
    assert "gains by hand" in str(e)
# the speed knob: more aggressive weights give a stiffer tilt loop
assert d.suggest_gains(sk, 10.0)["kp"] >= gs["kp"]

# ---- speed: a 10 s run is a second or so (the retry loop will do hundreds of them) --------------------------------------------------------------
import time
t0 = time.time()
d.simulate(d.example_robot())
assert time.time() - t0 < 5.0

print("PASS controls dyn engine")
