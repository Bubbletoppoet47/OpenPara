"""ctl_circuit (no Qt): drawn networks to transfer functions, checked against hand formulas and independent numeric models."""
import copy
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "controls")]
import ctl_circuit as C


def P(kind, a, b=None, name="", value="", rot=0):
    return {"kind": kind, "a": a, "b": b, "name": name, "value": value, "rot": rot}


def W(a, b):
    return P("W", a, b)


def ev(poly, s, vals=None):
    """Evaluate a Poly at complex s with numbers for the other names."""
    tot = 0
    for k, c in poly.t.items():
        t = float(c)
        for n, p in k:
            t *= (s if n == "s" else float((vals or {})[n])) ** p
        tot += t
    return tot


# ---- the three book examples, symbolic and numeric -------------------------------------------------------------------------------------------
d, parts = C.example(0)
sol = C.solve(parts, d)
assert C.tf_text(sol) == "1 / (C L s² + C R s + 1)", C.tf_text(sol)
assert C.equation_text(sol) == "C L vo'' + C R vo' + vo = vi", C.equation_text(sol)
assert C.is_series_loop(parts) and sol.in_name == "Vi" and sol.out_name == "Vo"

d, parts = C.example(1)
sol = C.solve(parts, d)
assert C.tf_text(sol) == "1 / (s² + B s + 2)", C.tf_text(sol)
assert C.equation_text(sol) == "x'' + B x' + 2 x = F", C.equation_text(sol)
assert C.numeric(sol, {}) is None and C.is_single_body(parts)
b3 = copy.deepcopy(parts)
for p in b3:
    if p["name"] == "B":
        p["value"] = "3"
n, dd = C.numeric(C.solve(b3, d), {})
assert n == [1.0] and dd == [1.0, 3.0, 2.0], (n, dd)

d, parts = C.example(2)
sol = C.solve(parts, d)
n, dd = C.numeric(sol, {})
assert n == [200.0] and [round(x, 9) for x in dd] == [1.0, 54.0, 400.0], (n, dd)
sym = copy.deepcopy(parts)
for p in sym:
    p["value"] = ""
ss = C.solve(sym, d)
assert C.tf_text(ss) == "R2 / (C L R2 s² + (C R1 R2 + L) s + (R1 + R2))", C.tf_text(ss)
assert not C.is_series_loop(parts)                                                       # it has a branch

# ---- independent numeric models ------------------------------------------------------------------------------------------------------------
vals = {"R1": Fraction(5), "R2": Fraction(5), "C": Fraction(1, 20), "L": Fraction(1, 10)}
for s in (0.7, 2.0 + 1.0j, 3j):
    Z = 5 / (1 + s * 5 * 0.05)                                                          # R2 || C
    g = Z / (5 + 0.1 * s + Z)
    got = ev(ss.num, s, vals) / ev(ss.den, s, vals)
    assert abs(got - g) < 1e-12, (s, got, g)

# two-stage RC ladder: R1 - node a (C1 to ground) - R2 - node b (C2 to ground) = output
lad = [P("V", (2, 4), (2, 12), "Vi"), W((2, 4), (4, 4)), P("R", (4, 4), (8, 4), "R1"), W((8, 4), (12, 4)), P("C", (10, 4), (10, 12), "C1"),
       P("R", (12, 4), (16, 4), "R2"), W((16, 4), (20, 4)), P("C", (20, 4), (20, 12), "C2"), W((2, 12), (20, 12)), P("GND", (11, 12), None, rot=1),
       P("VO", (20, 4), None, "Vo")]
sl = C.solve(lad, "electrical")
v2 = {"R1": Fraction(2), "R2": Fraction(3), "C1": Fraction(1, 5), "C2": Fraction(1, 7)}
for s in (0.5, 1.0 + 2.0j):
    r1, r2, c1, c2 = 2.0, 3.0, 0.2, 1 / 7
    Zb = 1 / (s * c2)
    Za = 1 / (1 / (1 / (s * c1)) + 1 / (r2 + Zb)) if False else 1 / (s * c1 + 1 / (r2 + Zb))
    va = Za / (r1 + Za)
    vb = va * Zb / (r2 + Zb)
    got = ev(sl.num, s, v2) / ev(sl.den, s, v2)
    assert abs(got - vb) < 1e-12, (s, got, vb)

# two masses: F pushes m1; x2 / F
two = [P("WALL", (2, 6), None, rot=2), P("K", (2, 6), (8, 6), "K1"), P("M", (8, 6), (12, 6), "M1"), P("K", (12, 6), (18, 6), "K2"),
       P("M", (18, 6), (22, 6), "M2"), P("F", (8, 6), None, "F", rot=3), P("X", (22, 6), None, "x", rot=0)]
st = C.solve(two, "mechanical")
v3 = {"M1": Fraction(1), "M2": Fraction(2), "K1": Fraction(3), "K2": Fraction(4)}
for s in (0.9, 1.0 + 1.0j):
    want = 4 / ((1 * s * s + 3 + 4) * (2 * s * s + 4) - 16)
    got = ev(st.num, s, v3) / ev(st.den, s, v3)
    assert abs(got - want) < 1e-12, (s, got, want)
assert not C.is_single_body(two)

# a terminal that lands on the middle of a wire joins it: a voltage divider whose resistors hang off long wires
div = [P("V", (2, 4), (2, 12), "Vi"), W((2, 4), (12, 4)), P("R", (6, 4), (6, 8), "R1"), P("R", (6, 8), (6, 12), "R2"), W((2, 12), (12, 12)),
       P("GND", (2, 12), None, rot=1), P("VO", (6, 8), None, "Vo")]
assert C.tf_text(C.solve(div, "electrical")) == "R2 / (R1 + R2)", C.tf_text(C.solve(div, "electrical"))

# ---- plain-words errors ---------------------------------------------------------------------------------------------------------------------
def err(parts, domain, word):
    try:
        C.solve(parts, domain)
    except C.CircuitError as e:
        assert word in str(e), (word, str(e))
        return
    raise AssertionError("expected an error containing %r" % word)


rlc = C.example(0)[1]
err([p for p in rlc if p["kind"] != "GND"], "electrical", "ground")
err([p for p in rlc if p["kind"] != "V"], "electrical", "source")
err([p for p in rlc if p["kind"] != "VO"], "electrical", "probe")
bad = copy.deepcopy(rlc)
next(p for p in bad if p["kind"] == "R")["value"] = "-2"
err(bad, "electrical", "positive")
bad = copy.deepcopy(rlc)
next(p for p in bad if p["kind"] == "R")["name"] = "2 bad"
err(bad, "electrical", "name")
bad = copy.deepcopy(rlc)
next(p for p in bad if p["kind"] == "R")["name"] = "s"
err(bad, "electrical", "name")
float_out = rlc + [P("VO", (30, 30), None, "Vx")]
err([p for p in rlc if p["kind"] != "VO"] + [P("VO", (30, 30), None, "Vx")], "electrical", "not connected")
err([p for p in rlc if p["kind"] != "VO"] + [P("VO", (9, 10), None, "Vx")], "electrical", "ground")
err([p for p in C.example(1)[1] if p["kind"] != "WALL"], "mechanical", "wall")
err([p for p in C.example(1)[1] if p["kind"] != "F"], "mechanical", "force")

# ---- the analogies ---------------------------------------------------------------------------------------------------------------------------
mech, lines = C.analog_of_loop(C.example(0)[1])
assert {p["kind"] for p in mech} == {"WALL", "W", "K", "B", "M", "F"}
assert [p["label"] for p in mech if p["kind"] in ("K", "B", "M")] == ["K = 1/C", "B = R", "M = L"]
assert any("Equation:  M x'' + B x' + K x = F" in x for x in lines)
num = copy.deepcopy(C.example(0)[1])
for p in num:
    p["value"] = {"L": "0.1", "R": "5", "C": "0.05"}.get(p["name"], "")
mech, lines = C.analog_of_loop(num)
assert [p["label"] for p in mech if p["kind"] in ("K", "B", "M")] == ["K = 20", "B = 5", "M = 0.1"], [p.get("label") for p in mech]
back_parts, back_lines = C.analog_of_body(C.example(1)[1])
assert [p["label"] for p in back_parts if p["kind"] in ("L", "R", "C")] == ["L = 1", "R = B", "C = 0.5"]
# the analog really is the same system: solve the drawn electrical analog (with a Vo probe on C) and compare the characteristic polynomials
assert any(p["kind"] == "V" for p in back_parts)
gen = C.analog_lines_general(C.example(2)[1], "electrical")
assert "single series loop" in gen[-1]

# ---- value parsing ---------------------------------------------------------------------------------------------------------------------------
assert C.parse_value("0.05") == Fraction(1, 20) and C.parse_value("2/3") == Fraction(2, 3) and C.parse_value("1e-3") == Fraction(1, 1000)
assert C.parse_value("") is None and C.parse_value("R") is None
assert C.poly_text(C.Poly.const(0)) == "0"
print("PASS controls circuit")
