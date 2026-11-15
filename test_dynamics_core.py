"""System dynamics solver (dev_addons/dynamics/dyn_core.py): checked against hand-derived results, no Qt."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "dev_addons", "dynamics"))
import numpy as np

import dyn_core as C

SRC = dict(wave="step", freq=1.0, delay=0.0, width=0.1)


def msd(m=2.0, k=200.0, c=20.0, rot=False):
    n = C.Net()
    n.add("INERTIA" if rot else "MASS", "m1", ["a"], **({"j": m} if rot else {"m": m}))
    n.add("TSPRING" if rot else "SPRING", "k1", ["a", "w"], k=k)
    n.add("RDAMPER" if rot else "DAMPER", "c1", ["a", "w"], c=c)
    n.add("FRAME" if rot else "WALL", "W", ["w"])
    n.add("TORQUE" if rot else "FORCE", "F1", ["a"], amp=1.0, **SRC)
    return C.build(n)


# ---- mass, spring, damper: wn = sqrt(k/m), zeta = c / (2 sqrt(k m)) ------------------------------------------------------------------
for rot in (False, True):
    s = msd(rot=rot)
    (m,) = s.modes()
    assert abs(m["wn"] - 10.0) < 1e-9 and abs(m["zeta"] - 0.5) < 1e-9 and abs(m["wd"] - 10 * math.sqrt(0.75)) < 1e-9
    assert s.stable() and abs(s.dc_gain(0, "a", "position") - 1 / 200.0) < 1e-12
    assert abs(s.undamped()[0] - 10.0) < 1e-9

# critical damping: c = 2 sqrt(k m) gives a double real pole at -sqrt(k/m)
s = msd(c=2 * math.sqrt(200 * 2))
p = s.poles()
assert np.allclose(p.real, -10.0, atol=1e-6) and np.allclose(p.imag, 0.0, atol=1e-6)
assert abs(s.modes()[0]["zeta"] - 1.0) < 1e-6 or all(abs(m["zeta"] - 1.0) < 1e-6 for m in s.modes())

# ---- time response against the closed-form underdamped step ----------------------------------------------------------------------------
s = msd()
run = C.simulate(s, 1.0, steps=2000)
t = run["t"]
wn, z = 10.0, 0.5
wd = wn * math.sqrt(1 - z * z)
exact = (1 - np.exp(-z * wn * t) * (np.cos(wd * t) + z / math.sqrt(1 - z * z) * np.sin(wd * t))) / 200.0
y = C.response(s, run, "a", "position")
assert np.max(np.abs(y - exact)) < 1e-8 * 1 + 1e-9, np.max(np.abs(y - exact))
v = C.response(s, run, "a", "velocity")
assert abs(v[0]) < 1e-12 and abs(v[-1]) < 1e-3
acc = C.response(s, run, "a", "acceleration")
assert abs(acc[1] - 0.5) < 5e-3                       # F/m right after the step (acceleration has direct feedthrough)
assert abs(s.gain(0, "a", "acceleration", 1e7j)[0] - 0.5) < 1e-4

# ---- gear pair: Ja + Jb/N^2 is the inertia seen at a; a damper on b appears as c/N^2 -------------------------------------------------------
n = C.Net()
n.add("INERTIA", "Ja", ["a"], j=0.01)
n.add("INERTIA", "Jb", ["b"], j=0.09)
n.add("GEAR", "G1", ["a", "b"], ratio=3.0)
n.add("RDAMPER", "c1", ["b", "w"], c=0.9)
n.add("FRAME", "W", ["w"])
n.add("TORQUE", "T1", ["a"], amp=1.0, **SRC)
s = C.build(n)
assert len(s.coords) == 1
assert abs(s.M[0, 0] - (0.01 + 0.09 / 9)) < 1e-12 and abs(s.Deff[0, 0] - 0.9 / 9) < 1e-12
assert abs(s.poles().real.min() + (0.9 / 9) / (0.01 + 0.09 / 9)) < 1e-9
assert abs(s.output("b", "velocity")[0][1] - 1 / 3.0) < 1e-12            # b turns 1/N as fast as a

# ---- rack and pinion with a spring on the straight side: wn^2 = k r^2 / (J + m r^2) ----------------------------------------------------------
n = C.Net()
n.add("INERTIA", "J", ["a"], j=0.004)
n.add("RACK", "R1", ["a", "b"], r=0.05)
n.add("MASS", "m", ["b"], m=2.0)
n.add("SPRING", "k", ["b", "w"], k=5000.0)
n.add("WALL", "W", ["w"])
n.add("TORQUE", "T1", ["a"], amp=1.0, **SRC)
s = C.build(n)
assert abs(s.undamped()[0] - math.sqrt(5000 * 0.05 ** 2 / (0.004 + 2.0 * 0.05 ** 2))) < 1e-9

# ---- lever: the far mass is reflected by the ratio squared ---------------------------------------------------------------------------------
n = C.Net()
n.add("MASS", "m1", ["a"], m=1.0)
n.add("LEVER", "L", ["a", "b"], ratio=-2.0)
n.add("MASS", "m2", ["b"], m=0.5)
n.add("SPRING", "k", ["a", "w"], k=90.0)
n.add("WALL", "W", ["w"])
n.add("FORCE", "F", ["a"], amp=1.0, **SRC)
s = C.build(n)
assert abs(s.M[0, 0] - (1.0 + 0.5 * 4)) < 1e-12 and abs(s.undamped()[0] - math.sqrt(90 / 3.0)) < 1e-9

# ---- a motor with a gearbox driving a link: the transfer function written out by hand ---------------------------------------------------
def motor_link(L):
    n = C.Net()
    n.add("MOTOR", "M1", ["s"], v=1.0, r=2.0, l=L, kt=0.05, ke=0.04, jm=1e-5, bm=1e-6, n=50.0, **SRC)
    n.add("LINK", "L1", ["s"], m=0.5, l=0.2, jcm=0.002, pose=0.0)
    return C.build(n)


for L in (1e-3, 0.0):
    s = motor_link(L)
    N, Kt, Ke, R = 50.0, 0.05, 0.04, 2.0
    J = 0.002 + 0.5 * 0.2 ** 2 + N ** 2 * 1e-5
    b = N ** 2 * 1e-6
    kg = 0.5 * C.G_ACCEL * 0.2
    for sv in (0.3j, 2.0 + 5j, 40.0j, 1.5):
        g = N * Kt / ((J * sv ** 2 + b * sv + kg) * (L * sv + R) + N ** 2 * Kt * Ke * sv)
        got = s.gain(0, "s", "position", sv)[0]
        assert abs(got - g) < 1e-9 * max(1.0, abs(g)), (L, sv, got, g)
    assert abs(s.dc_gain(0, "s", "position") - N * Kt / (R * kg)) < 1e-9
    assert s.stable()
    assert len(s.poles()) == (3 if L > 0 else 2)

# ---- a link above its pivot falls over: the system is flagged unstable, with a warning --------------------------------------------------------
n = C.Net()
n.add("LINK", "L1", ["a"], m=1.0, l=0.3, jcm=0.01, pose=180.0)
n.add("TORQUE", "T1", ["a"], amp=1.0, **SRC)
s = C.build(n)
assert not s.stable() and s.warnings and s.poles().real.max() > 1.0
assert abs(s.poles().real.max() - math.sqrt(C.G_ACCEL * 0.3 / (0.01 + 0.09))) < 1e-9

# ---- a free mass has a double pole at zero (rigid body) --------------------------------------------------------------------------------------
n = C.Net()
n.add("MASS", "m1", ["a"], m=2.0)
n.add("FORCE", "F", ["a"], amp=1.0, **SRC)
s = C.build(n)
assert np.allclose(s.poles(), 0) and not s.stable()
run = C.simulate(s, 2.0, steps=400)
assert abs(C.response(s, run, "a", "position")[-1] - 0.5 * 0.5 * 4) < 1e-9          # x = F t^2 / (2 m)

# ---- problems are reported in words ------------------------------------------------------------------------------------------------------------
n = C.Net()
n.add("SPRING", "k", ["a", "w"], k=1.0)
n.add("MASS", "m1", ["b"], m=1.0)
n.add("SPRING", "k2", ["a", "b"], k=1.0)
n.add("WALL", "W", ["w"])
try:
    C.build(n)
    raise AssertionError("a node with no mass should be refused")
except C.DynError as e:
    assert "no mass" in str(e)

n = C.Net()
n.add("MASS", "m1", ["a"], m=1.0)
n.add("INERTIA", "J1", ["a"], j=1.0)
try:
    C.build(n)
    raise AssertionError("joining t and r should be refused")
except C.DynError as e:
    assert "rack and pinion" in str(e)

# ---- the equations as text -----------------------------------------------------------------------------------------------------------------
txt = C.equations_text(msd())
assert "2 x_m1'' + 20 x_m1' + 200 x_m1 = F1" in txt, txt
assert "θ_m1" in C.equations_text(msd(rot=True))
assert "MOTOR EQUATIONS" in C.equations_text(motor_link(1e-3)) and "viscous damping" in C.equations_text(motor_link(0.0))
mt = C.modes_text(msd())
assert "wn = 10" in mt and "zeta = 0.5" in mt

# ---- source waveforms ---------------------------------------------------------------------------------------------------------------------
tt = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
assert list(C.wave_value(dict(amp=2, wave="step", delay=1.0), tt)) == [0, 0, 2, 2, 2]
assert list(C.wave_value(dict(amp=1, wave="pulse", delay=0.5, width=1.0), tt)) == [0, 1, 1, 0, 0]
assert np.allclose(C.wave_value(dict(amp=1, wave="ramp", delay=1.0), tt), [0, 0, 0, 0.5, 1.0])
assert np.allclose(C.wave_value(dict(amp=1, wave="sine", freq=0.25, delay=0), tt), np.sin(2 * math.pi * 0.25 * tt))
assert list(C.wave_value(dict(amp=1, wave="off"), tt)) == [0] * 5

# the matrix exponential
A = np.array([[0.0, 1.0], [-4.0, -0.4]])
E = C._expm(A * 0.37)
w, V = np.linalg.eig(A * 0.37)
assert np.allclose(E, (V @ np.diag(np.exp(w)) @ np.linalg.inv(V)).real, atol=1e-12)
print("PASS dynamics core")
