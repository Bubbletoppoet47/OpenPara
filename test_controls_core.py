"""Systems and Controls maths (dev_addons/controls/ctl_core.py): polynomial text, poles / zeros / gain / DC gain, worked answers.  No Qt."""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "dev_addons", "controls"))
import numpy as np

import ctl_core as C


def tf(n, d):
    return C.analyze(C.parse_poly(n), C.parse_poly(d))


def near(a, b, tol=1e-9):
    return abs(a - b) < tol


# ---- polynomial text -----------------------------------------------------------------------------------------------------------------------
P = C.parse_poly
for text, want in (("2s+3", [2, 3]), ("s^2+3s+2", [1, 3, 2]), ("S**2 + 3*S + 2", [1, 3, 2]), ("s²+3s+2", [1, 3, 2]), ("(s+1)(s+2)", [1, 3, 2]),
                   ("10(s+2)", [10, 20]), ("s(s+1)^2", [1, 2, 1, 0]), ("-s+4", [-1, 4]), ("2 s + 3", [2, 3]), ("5", [5]), ("1e-3 s", [1e-3, 0]),
                   ("s^2-s-2", [1, -1, -2]), ("(s+1)^3", [1, 3, 3, 1]), ("3(s+1)(s-2)", [3, -3, -6]), ("s^2 - s^2 + 4", [4]),
                   ("[1 3 2]", [1, 3, 2]), ("1, 3, 2", [1, 3, 2]), ("[0 0 2 3]", [2, 3]), ("2 3", [2, 3]), ("[2.5, -1]", [2.5, -1]),
                   ("1.5s", [1.5, 0]), ("−s+1", [-1, 1])):
    got = P(text)
    assert np.allclose(got, want), (text, got, want)
for bad in ("", "   ", "s+", "2s +* 3", "(s+1", "s^x", "s^-1", "s^1.5", "2s@3", "[1 a 2]", "s)", "^2"):
    try:
        P(bad)
        raise AssertionError("should have been refused: " + repr(bad))
    except C.TFError as e:
        assert str(e)

# ---- the book example 1.4.5.1:  G(s) = (2s+3) / (s^2+3s+2) ------------------------------------------------------------------------------------
a = tf("2s+3", "s^2+3s+2")
assert [near(z.real, -1.5) and z.imag == 0 for z in a.zeros] == [True]
assert [round(p.real, 9) for p in a.poles] == [-1.0, -2.0] and all(p.imag == 0 for p in a.poles)
assert near(a.gain, 2.0) and near(a.dc, 1.5)
assert a.order == 2 and a.rel_degree == 1 and a.kind == "strictly proper" and a.sys_type == 0 and a.stability == "stable" and not a.cancels
txt = C.report(a)
assert "2 (s + 1.5)" in txt and "(s + 1)(s + 2)" in txt and "Gain K = 2" in txt and "Zeros (roots of the numerator):   -1.5" in txt
assert "Poles (roots of the denominator): -1, -2" in txt and "G(0) = 3 / 2 = 1.5" in txt and "stable" in txt
assert "time constant 1 s" in txt and "time constant 0.5 s" in txt
# the same function written other ways gives the same answer
b = tf("[2 3]", "(s+1)(s+2)")
assert np.allclose(b.num, a.num) and np.allclose(b.den, a.den) and np.allclose(b.gain, a.gain)

# ---- scaling: multiplying top and bottom changes the polynomials but not the zeros, poles, K or DC gain --------------------------------------
c = tf("4s+6", "2s^2+6s+4")
assert near(c.gain, 2.0) and near(c.dc, 1.5) and np.allclose(sorted(p.real for p in c.poles), [-2, -1])

# ---- repeated poles, integrator (pole at the origin) -------------------------------------------------------------------------------------
a = tf("1", "s(s+1)^2")
assert math.isinf(a.dc) and a.sys_type == 1 and a.stability == "marginally stable"
assert "s(s + 1)²" in C.report(a) and "repeated 2 times" in C.report(a) and "integrator" in C.report(a)
a = tf("1", "s^2(s+3)")
assert a.sys_type == 2 and math.isinf(a.dc)
a = tf("s", "s^2+3s+2")                                   # a zero at the origin
assert a.dc == 0.0 and "zero at s = 0" in C.report(a)
a = tf("s+2", "s(s+5)")                                   # numerator and denominator both... only the denominator has s
assert math.isinf(a.dc)
a = tf("s(s+1)", "s(s+3)")                                # a common factor of s cancels in the DC gain
assert near(a.dc, 1.0 / 3.0) and a.sys_type == 0 and len(a.cancels) == 1

# ---- complex poles: natural frequency and damping ratio ------------------------------------------------------------------------------------
a = tf("25", "s^2+6s+25")                                 # wn = 5, zeta = 0.6
(m,) = a.modes
assert m["kind"] == "pair" and near(m["wn"], 5.0) and near(m["zeta"], 0.6) and near(m["wd"], 4.0) and near(a.dc, 1.0)
assert "(s² + 6s + 25)" in C.report(a) and "-3 + 4j" in C.report(a) and "damping ratio zeta = 0.6" in C.report(a)
a = tf("10(s+2)", "(s^2+2s+5)(s+3)")
assert near(a.gain, 10) and near(a.dc, 20.0 / 15.0) and a.stability == "stable" and "(s + 3)(s² + 2s + 5)" in C.report(a)
a = tf("1", "s^2+4")                                      # undamped: poles on the imaginary axis
assert a.stability == "marginally stable" and near(a.modes[0]["zeta"], 0.0)
a = tf("1", "s^2-s-2")                                    # roots 2 and -1
assert a.stability == "unstable" and sorted(round(p.real, 9) for p in a.poles) == [-1.0, 2.0] and "right half-plane" in C.report(a)
assert "(s - 2)" in C.report(a)
a = tf("1", "s^2+2s+1")                                   # a double root found numerically as -1 +- 1e-8 must still print as (s + 1)²
assert "(s + 1)²" in C.report(a) and "repeated 2 times" in C.report(a)
a = tf("1", "(s+1)^3")
assert "(s + 1)³" in C.report(a)

a = tf("1", "(s+2)^4")                                    # a quadruple root is merged back into one
assert "(s + 2)⁴" in C.report(a) or "(s + 2)^4" in C.report(a)
a = tf("1", "(s+1)(s+1.0005)")                            # two distinct close poles stay distinct
assert "repeated" not in C.report(a) and "(s + 1.0005)" in C.report(a)

# ---- cancelling pole and zero, improper, no poles / no zeros -----------------------------------------------------------------------------
a = tf("s+2", "(s+2)(s+5)")
assert len(a.cancels) == 1 and abs(a.cancels[0] + 2) < 1e-9 and "cancel" in C.report(a)
a = tf("s^2+1", "s+1")
assert a.kind == "improper" and a.rel_degree == -1 and "improper" in C.report(a)
a = tf("3", "2")                                          # a pure gain
assert near(a.gain, 1.5) and near(a.dc, 1.5) and a.poles == [] and a.zeros == [] and a.order == 0
assert "Zeros (roots of the numerator):   none" in C.report(a)
a = tf("s+1", "1")
assert a.kind == "improper" and a.poles == []

# ---- errors -----------------------------------------------------------------------------------------------------------------------------------
for n, d, word in (("1", "0", "denominator is zero"), ("0", "s+1", "numerator is zero")):
    try:
        tf(n, d)
        raise AssertionError("should fail")
    except C.TFError as e:
        assert word in str(e)

# ---- text helpers -----------------------------------------------------------------------------------------------------------------------------
assert C.poly_text([1, 3, 2]) == "s² + 3s + 2" and C.poly_text([2, 3]) == "2s + 3" and C.poly_text([-1, 0, 4]) == "-s² + 4" and C.poly_text([1, 0, 0, -1]) == "s³ - 1"
assert C.poly_text([0.5, 1.5]) == "0.5s + 1.5" and C.poly_text([1, -1]) == "s - 1" and C.poly_text([3]) == "3"
assert C.fmt(-1.0000000000000002) == "-1" and C.fmt(1.5) == "1.5" and C.fmt(0) == "0" and C.fmt(1 / 3) == "0.333333" and C.fmt(1e-15) == "0"
assert C.cfmt(complex(-1, 2)) == "-1 + 2j" and C.cfmt(complex(-1, -2)) == "-1 - 2j" and C.cfmt(complex(-1.5, 0)) == "-1.5"
ft = C.fraction_text("G(s) = ", "2s + 3", "s² + 3s + 2").splitlines()
assert len(ft) == 3 and set(ft[1].strip().replace("G(s) = ", "")) <= {"─"} or "─" in ft[1]
assert ft[0].strip() == "2s + 3" and ft[2].strip() == "s² + 3s + 2" and ft[1].startswith("G(s) = ")
assert C.factor_text([]) == "1" and C.factor_text([complex(0, 0)]) == "s"

# ---- the short answer and the block diagram -------------------------------------------------------------------------------------------------
a = tf("2s+3", "s^2+3s+2")
assert C.simple_report(a).splitlines() == ["G(s) = 2(s + 1.5) / ((s + 1)(s + 2))", "Zeros: -1.5", "Poles: -1, -2", "Gain K: 2", "DC gain G(0): 1.5", "Stable",
                                           "Step response:    y(t) = 1.5 - e^(-t) - 0.5e^(-2t)", "Impulse response: y(t) = e^(-t) + e^(-2t)"]
assert C.blocks_single(a) == [("2 (s + 1.5)", "(s + 1)(s + 2)")]
assert C.blocks_series(a) == [("2", None), ("s + 1.5", None), ("1", "s + 1"), ("1", "s + 2")]
a = tf("1", "s(s+1)^2")
r = C.simple_report(a).splitlines()
assert r[0] == "G(s) = 1 / (s(s + 1)²)" and "DC gain G(0): infinite (pole at s = 0)" in r and r[5].startswith("Marginally stable")
assert r[6] == "Step response:    y(t) = -2 + t + 2e^(-t) + t·e^(-t)" and r[7] == "Impulse response: y(t) = 1 - e^(-t) - t·e^(-t)", r
assert C.blocks_single(a) == [("1", "s(s + 1)²")] and C.blocks_series(a) == [("1", "s"), ("1", "(s + 1)²")]
a = tf("10(s+2)", "(s^2+2s+5)(s+3)")
r = C.simple_report(a)
assert "G(s) = 10(s + 2) / ((s + 3)(s² + 2s + 5))" in r and "Poles -1 ± 2j: wn = 2.23607 rad/s, zeta = 0.447214" in r
assert C.blocks_series(a)[-1] == ("1", "s² + 2s + 5")
assert "Unstable" in C.simple_report(tf("1", "s^2-s-2")) and "(s - 2)" in C.simple_report(tf("1", "s^2-s-2"))
assert "Poles ±1j" in C.simple_report(tf("s", "s^2+1"))
assert "cancel at -2" in C.simple_report(tf("s+2", "(s+2)(s+5)")) and "Improper" in C.simple_report(tf("s^2+1", "s+1"))
assert C.simple_report(tf("3", "2")).splitlines()[0] == "G(s) = 1.5" and C.blocks_single(tf("3", "2")) == [("1.5", None)] and C.blocks_series(tf("3", "2")) == [("1.5", None)]
assert C.simple_report(tf("-(s+1)", "(s+2)(s+3)")).splitlines()[0] == "G(s) = -(s + 1) / ((s + 2)(s + 3))"
assert C.blocks_single(tf("s", "s^2+1")) == [("s", "s² + 1")]
assert C.pair_text(complex(-1, 2)) == "-1 ± 2j" and C.pair_text(complex(0, 3)) == "±3j"

# ---- step and impulse responses: the book problems, worked by hand -------------------------------------------------------------------------------
def resp(n, d, kind):
    return C.response_of(tf(n, d), kind)


t_ = np.linspace(0, 4, 41)
# 1.4.5.5  impulse response of (s^2+3s+3) / (s^3+6s^2+11s+6) = 0.5 e^-t - e^-2t + 1.5 e^-3t
r = resp("s^2+3s+3", "s^3+6s^2+11s+6", "impulse")
assert r.text == "0.5e^(-t) - e^(-2t) + 1.5e^(-3t)" and near(r.y0, 1.0) and r.final == 0.0
assert np.allclose(r.eval(t_), 0.5 * np.exp(-t_) - np.exp(-2 * t_) + 1.5 * np.exp(-3 * t_))
assert r.pf_text == "0.5 / (s + 1) - 1 / (s + 2) + 1.5 / (s + 3)"
# step response of (2s+8) / (s^3+5s^2+8s+4) = 2 - 6e^-t + 4e^-2t + 2t e^-2t   (a repeated pole)
r = resp("2s+8", "s^3+5s^2+8s+4", "step")
assert r.text == "2 - 6e^(-t) + 4e^(-2t) + 2t·e^(-2t)" and near(r.y0, 0.0) and near(r.final, 2.0)
assert np.allclose(r.eval(t_), 2 - 6 * np.exp(-t_) + 4 * np.exp(-2 * t_) + 2 * t_ * np.exp(-2 * t_))
assert r.pf_text == "2 / s - 6 / (s + 1) + 4 / (s + 2) + 2 / (s + 2)²"
# closed loop 45(s+6) / ((s^2+65s+354) s): (s+6) cancels, leaving 45 / (s (s+59)); the step response has a double pole at the origin
a = tf("45(s+6)", "(s^2+65s+354)s")
assert len(a.cancels) == 1 and abs(a.cancels[0] + 6) < 1e-6
r = C.response_of(a, "step")
t3 = np.linspace(0, 0.3, 31)
assert np.allclose(r.eval(t3), 45 / 59 * t3 - 45 / 59 ** 2 * (1 - np.exp(-59 * t3)), atol=1e-12)
assert r.text == "-0.0129273 + 0.762712t + 0.0129273e^(-59t)" and r.final is None and "without limit" in r.final_note
assert "cancel at -6" in C.simple_report(a)
r = C.response_of(a, "impulse")
assert np.allclose(r.eval(t3), 45 / 59 * (1 - np.exp(-59 * t3))) and near(r.final, 45 / 59)

# ---- special cases ---------------------------------------------------------------------------------------------------------------------------
assert resp("1", "s^2+2s+5", "impulse").text == "0.5e^(-t)sin(2t)"
assert resp("1", "s^2+2s+5", "step").text == "0.2 - e^(-t)(0.2cos(2t) + 0.1sin(2t))"
assert resp("1", "s^2+4", "step").text == "0.25 - 0.25cos(2t)" and "oscillates" in resp("1", "s^2+4", "step").final_note
assert resp("1", "s(s+1)", "step").text == "-1 + t + e^(-t)" and resp("1", "s(s+1)", "impulse").final == 1.0
assert resp("3", "2", "impulse").text == "1.5δ(t)" and resp("3", "2", "step").text == "1.5" and resp("3", "2", "impulse").terms == []
assert resp("s^2+1", "s+1", "step").text == "δ(t) + 1 - 2e^(-t)" and resp("s^2+1", "s+1", "impulse").text == "-δ(t) + δ'(t) + 2e^(-t)"
assert resp("1", "s^2-s-2", "step").final is None and "grows" in resp("1", "s^2-s-2", "step").final_note
assert resp("s", "s+1", "impulse").text == "δ(t) - e^(-t)"
assert "Step response:  Y(s) = G(s) / s" in C.report(tf("2s+8", "s^3+5s^2+8s+4")) and "y(0+) = 0;  final value: 2" in C.report(tf("2s+8", "s^3+5s^2+8s+4"))


# ---- the analytical answers agree with an independent numerical simulation (state space + matrix exponential) --------------------------------------
def expm(A):
    n = np.linalg.norm(A, 1)
    k = max(0, int(math.ceil(math.log2(n / 0.5))) + 1) if n > 0.5 else 0
    X, R, term = A / 2 ** k, np.eye(len(A)), np.eye(len(A))
    for i in range(1, 25):
        term = term @ X / i
        R = R + term
    for _ in range(k):
        R = R @ R
    return R


def simulate(num, den, t, kind):
    """Controllable canonical form of a proper G(s); returns y(t) without the delta term."""
    d0 = float(den[0])
    den = np.asarray(den, float) / d0
    num = np.asarray(num, float) / d0
    n = len(den) - 1
    num = np.concatenate([np.zeros(n + 1 - len(num)), num])
    D = num[0]
    c = num[1:] - D * den[1:]
    A = np.zeros((n, n))
    A[:-1, 1:] = np.eye(n - 1)
    A[-1, :] = -den[1:][::-1]
    B = np.zeros(n)
    B[-1] = 1.0
    C_ = c[::-1]
    y = []
    for tk in t:
        E = expm(A * tk)
        if kind == "impulse":
            y.append(C_ @ E @ B)
        else:
            big = np.zeros((n + 1, n + 1))                       # integral of e^(A tau) B from 0 to t: the corner of expm([[A, B], [0, 0]] t)
            big[:n, :n], big[:n, n] = A * tk, B * tk
            x = expm(big)[:n, n]
            y.append(C_ @ x + D)
    return np.array(y)


CASES = [("2s+3", "s^2+3s+2"), ("s^2+3s+3", "(s+1)(s+2)(s+3)"), ("2s+8", "s^3+5s^2+8s+4"), ("1", "s^2+2s+5"), ("10(s+2)", "(s^2+2s+5)(s+3)"),
         ("1", "s^2+4"), ("1", "s(s+1)"), ("1", "s^2"), ("1", "s(s+1)^2"), ("1", "s^2-s-2"), ("s+2", "(s+2)(s+5)"), ("s+3", "s+1"), ("1", "(s+1)^3"),
         ("5", "s^2+0.4s+4"), ("3", "(s+1)(s^2+2s+10)^2"), ("45(s+6)", "(s^2+65s+354)s"), ("s", "s^2+s+1"), ("1", "s^2(s+2)")]
for n_, d_ in CASES:
    a = tf(n_, d_)
    for kind in ("step", "impulse"):
        r = C.response_of(a, kind)
        tt = np.linspace(0, r.horizon, 25)
        ref = simulate(a.num, a.den, tt, kind)
        got = r.eval(tt)
        err = np.max(np.abs(got - ref)) / max(1.0, np.max(np.abs(ref)))
        assert err < 1e-7, (n_, d_, kind, err, r.text)
        assert r.horizon > 0 and np.all(np.isfinite(got))

# ---- Routh-Hurwitz: the book's arrays, special cases, and a random cross-check against the roots ----------------------------------------------------
def cols(r):
    return [row["cells"] for row in r.rows]


r = C.routh([1, 15, 85, 225, 274, 120])                                                   # book 2.3 worked example
assert cols(r) == [["1", "85", "274"], ["15", "225", "120"], ["70", "266"], ["168", "120"], ["216"], ["120"]], cols(r)
assert r.verdict.startswith("Stable") and r.changes == 0 and r.necessary[0] and r.check.endswith("(agrees).")
r = C.routh([1, 1, 4, 24, 3, 63])                                                         # book 2.3.3: row of zeros, auxiliary equation 21 s^2 + 63
assert cols(r) == [["1", "4", "3"], ["1", "24", "63"], ["-20", "-60"], ["21", "63"], ["42"], ["63"]], cols(r)
assert [row["kind"] for row in r.rows][3:5] == ["aux_source", "aux_derivative"]
assert r.changes == 2 and r.verdict.startswith("Unstable") and abs(abs(r.aux[0][1][0].imag) - math.sqrt(3)) < 1e-9 and r.aux[0][0] == "21s² + 63", r.aux
assert any("21s² + 63 = 0" in n for n in r.notes) and r.rhp_roots == 2 and r.axis_roots == 2
r = C.routh([1, 1, 2, 8])                                                                 # 2.3.4.1
assert cols(r) == [["1", "2"], ["1", "8"], ["-6"], ["8"]] and r.changes == 2 and r.verdict.startswith("Unstable: 2 sign changes")
r = C.routh([1, 1, 3, 5, 10])                                                             # 2.3.4.2
assert cols(r) == [["1", "3", "10"], ["1", "5"], ["-2", "10"], ["10"], ["10"]] and r.changes == 2
r = C.routh([1, 0, 2, 3])                                                                 # a zero alone in the first column: epsilon
assert cols(r)[1][0] == "ε" and cols(r)[2][0] == "-3/ε" and r.rows[1]["kind"] == "eps" and r.changes == 2 and not r.necessary[0] and "s^2" in r.necessary[1]
r = C.routh([1, 0, 1])                                                                    # roots on the imaginary axis only
assert r.verdict.startswith("Marginally stable") and r.changes == 0 and r.imag == 2
r = C.routh([2, 4, 2, 0])                                                                 # root at s = 0: taken out
assert r.verdict.startswith("Marginally stable") and any("A factor s" in n for n in r.notes), r.notes
r = C.routh([-1, -3, -2])                                                                 # negative leading coefficient is flipped
assert r.verdict.startswith("Stable") and any("multiplied by -1" in n for n in r.notes)
for bad in ([5], [0, 0, 3]):
    try:
        C.routh(bad)
        raise AssertionError("expected TFError")
    except C.TFError:
        pass
rng = np.random.default_rng(7)
checked = 0
for _ in range(600):
    deg = int(rng.integers(2, 9))
    q = [int(x) for x in rng.integers(-4, 10, size=deg + 1)]
    if q[0] == 0 or q[-1] == 0:
        continue
    roots = np.roots(q)
    re = np.abs(roots.real)
    if np.any((re > 1e-9) & (re < 1e-4)):                                                    # too close to the axis for the root test to be trusted
        continue
    r = C.routh(q)
    want_rhp = int(np.sum(roots.real > 1e-7))
    want_axis = int(np.sum(re <= 1e-7))
    assert r.rhp == want_rhp, (q, r.rhp, want_rhp, [row["cells"] for row in r.rows])
    if want_rhp == 0:
        assert r.verdict.startswith("Stable" if want_axis == 0 else "Marginally"), (q, r.verdict)
    checked += 1
assert checked > 300, checked
print("PASS controls core")
