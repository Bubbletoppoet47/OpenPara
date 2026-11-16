"""ctl_core.py - the maths of the Systems and Controls add-on (no Qt, so it can be tested on its own).

Section 1: transfer functions.  A transfer function G(s) = num(s) / den(s) is typed as text (`2s+3`, `s^2+3s+2`, `(s+1)(s+2)`, or a coefficient
list `[1 3 2]`), turned into coefficient arrays (highest power first), and analysed: zeros, poles, gain K, DC gain, stability, order and type,
and the factored "pole-zero" form, all as plain text a student can compare with the book.
"""
import math
import re

import numpy as np

REL = 1e-6                      # roots closer than this (relative) are treated as one repeated root / a cancelling pole and zero


class TFError(Exception):
    """Something wrong with the transfer function, in words for the person at the window."""


# --------------------------------------------------------------------------------------------------- polynomial text -> coefficients
def trim(c):
    """Drop leading zeros of a coefficient array (highest power first); [0] for the zero polynomial."""
    c = np.atleast_1d(np.asarray(c, float))
    nz = np.nonzero(c)[0]
    return c[nz[0]:] if len(nz) else np.zeros(1)


_NUM = r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_TOKEN = re.compile(rf"\s*(?:({_NUM})|([sS])|(\*\*|\^)|([-+*()]))")


def _tokens(text):
    pos, out = 0, []
    text = text.replace("²", "^2").replace("³", "^3").replace("·", "*").replace("−", "-")
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _TOKEN.match(text, pos)
        if not m:
            bad = text[pos:].lstrip()[0]
            raise TFError(f"I could not read '{bad}'. Use numbers, s, + - * ^ and brackets, for example 2s+3 or (s+1)(s+2).")
        num, s, pw, op = m.groups()
        if num is not None:
            out.append(("num", float(num)))
        elif s:
            out.append(("s", None))
        elif pw:
            out.append(("pow", None))
        else:
            out.append((op, None))
        pos = m.end()
    return out


class _Parser:
    """expr := term {(+|-) term};  term := factor {[*] factor};  factor := [-] atom [^ int];  atom := number | s | ( expr )"""

    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i][0] if self.i < len(self.t) else None

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()[0]
            w = self.term()
            v = np.polyadd(v, w if op == "+" else -w)
        return v

    def term(self):
        v = self.factor()
        while True:
            k = self.peek()
            if k == "*":
                self.take()
                v = np.polymul(v, self.factor())
            elif k in ("num", "s", "("):                       # implicit multiplication: 2s, 3(s+1), (s+1)(s+2), s(s+1)
                v = np.polymul(v, self.factor())
            else:
                return v

    def factor(self):
        sign = 1.0
        while self.peek() in ("-", "+"):
            if self.take()[0] == "-":
                sign = -sign
        v = self.atom()
        if self.peek() == "pow":
            self.take()
            if self.peek() == "(":                              # s^(2)
                self.take()
                e = self.take()
                if e[0] != "num" or self.peek() != ")":
                    raise TFError("A power must be a whole number, for example s^2.")
                self.take()
            else:
                e = self.take() if self.peek() == "num" else (None, None)
            n = e[1]
            if n is None or n != int(n) or n < 0 or n > 60:
                raise TFError("A power must be a whole number from 0 up, for example s^2.")
            r = np.ones(1)
            for _ in range(int(n)):
                r = np.polymul(r, v)
            v = r
        return sign * v

    def atom(self):
        if self.i >= len(self.t):
            raise TFError("The expression ends too early (is something missing after a + - * or ^?).")
        k, val = self.take()
        if k == "num":
            return np.array([val])
        if k == "s":
            return np.array([1.0, 0.0])
        if k == "(":
            v = self.expr()
            if self.peek() != ")":
                raise TFError("A bracket is not closed.")
            self.take()
            return v
        raise TFError("I did not expect '" + {"pow": "^", "*": "*", ")": ")", "+": "+", "-": "-"}.get(k, k) + "' there.")


def parse_poly(text):
    """'2s+3' -> [2, 3];  's^2+3s+2' -> [1, 3, 2];  '(s+1)(s+2)' -> [1, 3, 2];  '[1 3 2]' or '1, 3, 2' -> [1, 3, 2].  Raises TFError."""
    t = str(text).strip()
    if not t:
        raise TFError("Enter a polynomial in s (for example s^2+3s+2) or a list of coefficients (for example [1 3 2]).")
    body = t[1:-1] if (t.startswith("[") and t.endswith("]")) else t
    parts = [p for p in re.split(r"[\s,;]+", body.strip()) if p]
    if t.startswith("[") or ("," in t and "s" not in t.lower() and "(" not in t) or (len(parts) > 1 and all(_is_number(p) for p in parts)):
        if not parts or not all(_is_number(p) for p in parts):
            raise TFError("A coefficient list holds numbers only, highest power first, for example [1 3 2].")
        return trim([float(p) for p in parts])
    p = _Parser(_tokens(t))
    v = p.expr()
    if p.i != len(p.t):
        raise TFError("I did not expect '" + {"pow": "^", "num": "a number", "s": "s"}.get(p.t[p.i][0], p.t[p.i][0]) + "' there.")
    return trim(v)


def _is_number(p):
    try:
        float(p)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------------------------------- number / polynomial text
def fmt(x, digits=6):
    """-1.0000000000000002 -> '-1';  1.5 -> '1.5';  0.333333 -> '0.333333'."""
    x = float(x)
    if x == 0 or abs(x) < 1e-12:
        return "0"
    r = float(f"{x:.{digits}g}")
    if abs(r - round(r)) < 1e-9 * max(1.0, abs(r)):
        r = float(round(r))
    s = f"{r:.{digits}g}"
    return s[:-2] if s.endswith(".0") else s


def cfmt(z, digits=6):
    """Complex number as '-1 + 2j'; real numbers without the imaginary part."""
    z = complex(z)
    if abs(z.imag) < 1e-9 * max(1.0, abs(z)):
        return fmt(z.real, digits)
    re_, im = fmt(z.real, digits), fmt(abs(z.imag), digits)
    sign = "-" if z.imag < 0 else "+"
    return f"{re_} {sign} {im}j" if re_ != "0" else (f"{'-' if z.imag < 0 else ''}{im}j")


SUP = {2: "²", 3: "³"}


def poly_text(c):
    """[1, 3, 2] -> 's² + 3s + 2'."""
    c = trim(c)
    n = len(c) - 1
    out = ""
    for i, a in enumerate(c):
        p = n - i
        if abs(a) < 1e-15:
            continue
        mag = abs(a)
        body = "" if (abs(mag - 1) < 1e-12 and p > 0) else fmt(mag)
        if p == 0:
            term = fmt(mag)
        else:
            sp = "s" if p == 1 else f"s{SUP.get(p, '^' + str(p))}"
            term = body + sp
        out += (" - " if a < 0 else " + ") + term if out else (("-" if a < 0 else "") + term)
    return out or "0"


# --------------------------------------------------------------------------------------------------- analysis
def _group(roots):
    """Cluster numerically equal roots -> list of (root, multiplicity).  Conjugates stay separate (their pairing is done by the caller)."""
    items = []
    for r in sorted(roots, key=lambda z: (round(z.real, 9), round(z.imag, 9))):
        for k, (q, m) in enumerate(items):
            if abs(r - q) <= REL * 10 * max(1.0, abs(q)):
                items[k] = ((q * m + r) / (m + 1), m + 1)
                break
        else:
            items.append((r, 1))
    return items


def _order(roots):
    """Book order: the root nearest the right (closest to the origin or furthest right) first, a conjugate pair with the positive part first."""
    return sorted(roots, key=lambda z: (-round(z.real, 9), -z.imag))


def _snap(roots, poly=None):
    """Remove the dust from numerically found roots: -1.0000000000000002 -> -1, 3e-17j -> 0.  A repeated root comes out of the numerics as a
    little cluster (a triple root at -1 appears as -1 plus a tiny complex pair); when `poly` (the coefficients the roots came from) is given,
    such clusters are merged if the merged roots still rebuild the polynomial."""
    out = []
    for z in roots:
        z = complex(z)
        scale = max(1.0, abs(z))
        re_, im = z.real, z.imag
        if abs(im) < 1e-9 * scale:
            im = 0.0
        if abs(re_) < 1e-12 * scale:
            re_ = 0.0
        out.append(complex(re_, im))
    if poly is not None and len(out) > 1:
        merged = []
        for r in out:
            for k, (q, m) in enumerate(merged):
                if abs(r - q) <= 1e-3 * max(1.0, abs(q)):
                    merged[k] = ((q * m + r) / (m + 1), m + 1)
                    break
            else:
                merged.append((r, 1))
        if any(m > 1 for _q, m in merged):
            cand = []
            for q, m in merged:
                if m > 1:
                    q = complex(q.real if abs(q.real) > 1e-12 else 0.0, q.imag if abs(q.imag) > 1e-9 * max(1.0, abs(q)) else 0.0)
                cand += [q] * m
            rebuilt = np.real(np.poly(cand)) * poly[0]
            if np.allclose(rebuilt, poly, rtol=1e-10, atol=1e-12 * float(np.max(np.abs(poly)))):
                out = cand
    return _order(out)


def factor_list(roots):
    """Roots -> ['(s + 1)', '(s + 2)²']; a complex pair becomes one quadratic '(s² + 2s + 5)'; a root at zero is 's'.  [] for no roots."""
    roots = _snap(roots)
    real = [r for r in roots if r.imag == 0]
    cplx = [r for r in roots if r.imag > 0]
    pieces = []
    for r, m in sorted(_group([complex(x.real, 0) for x in real]), key=lambda t: -t[0].real):
        base = "s" if abs(r.real) < 1e-12 else f"(s {'+' if -r.real > 0 else '-'} {fmt(abs(r.real))})"
        pieces.append(base + (SUP.get(m, f"^{m}") if m > 1 else ""))
    for r, m in sorted(_group(cplx), key=lambda t: (-t[0].real, t[0].imag)):
        b, c = -2 * r.real, abs(r) ** 2
        quad = "s²" + ("" if abs(b) < 1e-12 else f" {'+' if b > 0 else '-'} {fmt(abs(b))}s") + f" {'+' if c >= 0 else '-'} {fmt(abs(c))}"
        pieces.append(f"({quad})" + (SUP.get(m, f"^{m}") if m > 1 else ""))
    return pieces


def factor_text(roots, var="s"):
    """Roots -> '(s + 1)(s + 2)²' ('1' when there are none)."""
    return "".join(factor_list(roots)) or "1"


def fraction_text(prefix, top, bottom):
    """Three lines of monospace text: `prefix` `top` over a bar over `bottom`."""
    w = max(len(top), len(bottom)) + 2
    pad = " " * len(prefix)
    return "\n".join([pad + top.center(w).rstrip(), prefix + "─" * w, pad + bottom.center(w).rstrip()])


class Analysis:
    """Everything the Transfer function section shows.  Attributes: num, den (arrays), zeros, poles (complex lists), gain, dc, dc_note,
    order, rel_degree, kind ('strictly proper' | 'proper' | 'improper'), sys_type, stability ('stable' | 'unstable' | 'marginally stable'),
    cancels (list of complex), modes (list of dicts)."""


def analyze(num, den):
    num, den = trim(num), trim(den)
    if not np.any(den):
        raise TFError("The denominator is zero, so G(s) is not defined.")
    if not np.any(num):
        raise TFError("The numerator is zero, so G(s) = 0 for every s.")
    a = Analysis()
    a.num, a.den = num, den
    a.zeros = _snap(np.roots(num), num) if len(num) > 1 else []
    a.poles = _snap(np.roots(den), den) if len(den) > 1 else []
    a.gain = float(num[0] / den[0])
    a.order = len(den) - 1
    a.rel_degree = (len(den) - 1) - (len(num) - 1)
    a.kind = "strictly proper" if a.rel_degree > 0 else ("proper" if a.rel_degree == 0 else "improper")
    # a pole and a zero at the same place cancel
    a.cancels = []
    free_z = list(a.zeros)
    for p in a.poles:
        for k, z in enumerate(free_z):
            if abs(p - z) <= REL * 10 * max(1.0, abs(p)):
                a.cancels.append(p)
                del free_z[k]
                break
    # type = number of poles at the origin (after cancelling common s factors)
    nz0 = _trailing_zeros(num)
    np0 = _trailing_zeros(den)
    a.sys_type = max(np0 - nz0, 0)
    # DC gain G(0): cancel common powers of s first
    n_last, d_last = num[len(num) - 1 - nz0], den[len(den) - 1 - np0]
    if np0 > nz0:
        a.dc, a.dc_note = math.inf, "there is a pole at s = 0 (an integrator), so G(0) is infinite"
    elif np0 < nz0:
        a.dc, a.dc_note = 0.0, "there is a zero at s = 0, so G(0) = 0"
    else:
        a.dc = float(n_last / d_last)
        a.dc_note = f"G(0) = {fmt(n_last)} / {fmt(d_last)}" + ("" if nz0 == 0 else "  (after cancelling the common factor of s)")
    # stability from the poles (a cancelled pole is still reported, but flagged)
    if not a.poles:
        a.stability = "stable"
    else:
        mx = max(p.real / max(1.0, abs(p)) for p in a.poles)
        a.stability = "unstable" if mx > 1e-9 else ("marginally stable" if mx > -1e-9 else "stable")
    # modes of the poles (repeated poles are listed once with their multiplicity)
    a.modes = []
    for p, m in sorted(_group([q for q in a.poles if q.imag == 0]), key=lambda t: -t[0].real):
        p = complex(p.real, 0.0)
        a.modes.append({"pole": p, "kind": "real", "mult": m, "tau": (1 / -p.real) if p.real < -1e-12 else None})
    for p, m in sorted(_group([q for q in a.poles if q.imag > 0]), key=lambda t: (-t[0].real, t[0].imag)):
        wn = abs(p)
        a.modes.append({"pole": p, "kind": "pair", "mult": m, "wn": wn, "zeta": -p.real / wn, "wd": p.imag})
    return a


def _trailing_zeros(c):
    n = 0
    for v in c[::-1]:
        if abs(v) < 1e-15 and n < len(c) - 1:
            n += 1
        else:
            break
    return n


def pole_zero_form(a):
    """K (s - z1)... / ((s - p1)...) as text lines (three lines of a fraction)."""
    top = factor_text(a.zeros)
    bot = factor_text(a.poles)
    k = a.gain
    if abs(k - 1) < 1e-12 and top != "1":
        head = top
    elif abs(k + 1) < 1e-12 and top != "1":
        head = "-" + top
    else:
        head = fmt(k) + ("" if top == "1" else " " + top)
    return fraction_text("G(s) = ", head, bot)


def report(a):
    """The whole worked answer as plain text."""
    L = []
    L.append("Transfer function")
    L.append(fraction_text("G(s) = ", poly_text(a.num), poly_text(a.den)))
    L.append("")
    L.append("Pole-zero model")
    L.append(pole_zero_form(a))
    L.append("")
    L.append(f"Gain K = {fmt(a.gain)}   (leading coefficient of the numerator / leading coefficient of the denominator)")
    L.append("Zeros (roots of the numerator):   " + (", ".join(cfmt(z) for z in a.zeros) if a.zeros else "none"))
    L.append("Poles (roots of the denominator): " + (", ".join(cfmt(p) for p in a.poles) if a.poles else "none"))
    if a.cancels:
        L.append("Note: " + ", ".join(cfmt(c) for c in a.cancels) + " is both a pole and a zero, so they cancel in the reduced model.")
    L.append("")
    L.append("DC gain")
    if math.isinf(a.dc):
        L.append(f"  {a.dc_note}")
    else:
        L.append(f"  {a.dc_note}" + ("" if a.dc == 0 else f" = {fmt(a.dc)}"))
        L.append(f"  DC gain = {fmt(a.dc)}" + (f"   (for a constant input of 1 the output settles at {fmt(a.dc)})" if a.stability == "stable" else
                                               "   (not a settling value: the system is not stable)"))
    L.append("")
    L.append("Properties")
    L.append(f"  Order {a.order};  relative degree {a.rel_degree} ({a.kind});  system type {a.sys_type}"
             + ("  (no pole at the origin)" if a.sys_type == 0 else "  (that many integrators)"))
    why = {"stable": "every pole has a negative real part (left half-plane)",
           "unstable": "a pole has a positive real part (right half-plane)",
           "marginally stable": "a pole sits on the imaginary axis (and none is in the right half-plane)"}[a.stability]
    L.append(f"  Stability: {a.stability} - {why}")
    if a.kind == "improper":
        L.append("  Note: the numerator has a higher power of s than the denominator (improper), so this cannot be built as a real physical system.")
    for m in a.modes:
        p = m["pole"]
        rep_ = f" (repeated {m['mult']} times)" if m["mult"] > 1 else ""
        if m["kind"] == "pair":
            L.append(f"  Pole pair {cfmt(p)}{rep_}:  natural frequency wn = {fmt(m['wn'])} rad/s,  damping ratio zeta = {fmt(m['zeta'])},  "
                     f"damped frequency wd = {fmt(m['wd'])} rad/s")
        elif m["tau"] is not None:
            L.append(f"  Pole {cfmt(p)}{rep_}:  time constant {fmt(m['tau'])} s")
        else:
            L.append(f"  Pole {cfmt(p)}{rep_}:  {'at the origin (integrator)' if p == 0 else 'growing exponential'}")
    for kind, title, ys in (("step", "Step response", "G(s) / s"), ("impulse", "Impulse response", "G(s)")):
        r = response_of(a, kind)
        L.append("")
        L.append(f"{title}:  Y(s) = {ys}")
        L.append(f"  Y(s) = {r.pf_text}")
        L.append(f"  y(t) = {r.text}")
        L.append(f"  y(0+) = {fmt(r.y0)};  final value: {r.final_note}")
    return "\n".join(L)


# --------------------------------------------------------------------------------------------------- the short answer and the block diagram
def pz_parts(a):
    """(K text, zero factors text, pole factors text) of the pole-zero form; the zero / pole text is '' when there are none."""
    k = a.gain
    ktxt = "" if abs(k - 1) < 1e-12 else ("-" if abs(k + 1) < 1e-12 else fmt(k))
    return ktxt, "".join(factor_list(a.zeros)), "".join(factor_list(a.poles))


_SINGLE = re.compile(r"^-?[\d.e+]*(\([^()]*\)|s)?[²³⁴⁵⁶⁷⁸⁹]?(\^\d+)?$")


def _wrap(x):
    """Brackets around a product of several factors, none around a single factor ('2(s + 1.5)', 's', '(s² + 1)')."""
    return x if _SINGLE.match(x) else "(" + x + ")"


def pz_one_line(a):
    """K(s + z1)... / ((s + p1)...) on one line."""
    ktxt, top, bot = pz_parts(a)
    num = (ktxt + top) or "1"
    return _wrap(num) + " / " + _wrap(bot) if bot else num


def pair_text(p):
    """-1 + 2j -> '-1 ± 2j';  0 + 1j -> '±1j'."""
    re_, im = fmt(p.real), fmt(abs(p.imag))
    return f"±{im}j" if re_ == "0" else f"{re_} ± {im}j"


def simple_report(a):
    """The short answer: G(s) in pole-zero form, zeros, poles, gain, DC gain, stability - and a line only for what needs a warning."""
    L = ["G(s) = " + pz_one_line(a)]
    L.append("Zeros: " + (", ".join(cfmt(z) for z in a.zeros) if a.zeros else "none"))
    L.append("Poles: " + (", ".join(cfmt(p) for p in a.poles) if a.poles else "none"))
    L.append(f"Gain K: {fmt(a.gain)}")
    L.append("DC gain G(0): " + ("infinite (pole at s = 0)" if math.isinf(a.dc) else fmt(a.dc)))
    L.append({"stable": "Stable", "unstable": "Unstable (a pole is in the right half-plane)",
              "marginally stable": "Marginally stable (a pole is on the imaginary axis)"}[a.stability])
    L.append("Step response:    y(t) = " + response_of(a, "step").text)
    L.append("Impulse response: y(t) = " + response_of(a, "impulse").text)
    for m in a.modes:
        if m["kind"] == "pair":
            L.append(f"Poles {pair_text(m['pole'])}: wn = {fmt(m['wn'])} rad/s, zeta = {fmt(m['zeta'])}")
    if a.cancels:
        L.append("Pole and zero cancel at " + ", ".join(cfmt(c) for c in a.cancels) + " (the responses use the reduced G(s))")
    if a.kind == "improper":
        L.append("Improper: the numerator is a higher power of s than the denominator")
    return "\n".join(L)


def _strip(x):
    """'(s² + 1)' -> 's² + 1': a lone bracketed factor needs no brackets inside a block."""
    return x[1:-1] if re.fullmatch(r"\([^()]*\)", x) else x


def blocks_single(a):
    """One block holding G(s): [(top, bottom)] with bottom None when there is no denominator."""
    ktxt, top, bot = pz_parts(a)
    num = (ktxt + (" " if ktxt not in ("", "-") and top else "") + top) or "1"
    return [(_strip(num), _strip(bot) if bot else None)]


def blocks_series(a):
    """G(s) as blocks in a row: the gain K, one block per zero factor (s + z), one per pole factor 1 / (s + p).  [(top, bottom)]"""
    out = []
    if abs(a.gain - 1) > 1e-12:
        out.append((fmt(a.gain), None))
    for f in factor_list(a.zeros):
        out.append((_strip(f), None))
    for f in factor_list(a.poles):
        out.append(("1", _strip(f)))
    return out or [("1", None)]


# --------------------------------------------------------------------------------------------------- step and impulse response
class Response:
    """The analytical response of G(s) to a unit step or a unit impulse.  Attributes: kind, terms (list of dicts: kind 'real' | 'osc', n = power
    of t, sigma, omega, c for a real term, a and b for an oscillating one (a cos wt + b sin wt)), deltas ({k: coefficient of the k-th derivative of
    delta(t)}), text (y(t) = ...), pf_text (Y(s) in partial fractions), y0 (y at 0+), final (a number, or None), final_note, horizon (s)."""

    def eval(self, t):
        t = np.asarray(t, float)
        y = np.zeros_like(t)
        for m in self.terms:
            base = np.exp(m["sigma"] * t) * (t ** m["n"] / math.factorial(m["n"]) if m["n"] else 1.0)
            if m["kind"] == "real":
                y = y + m["c"] * base
            else:
                y = y + base * (m["a"] * np.cos(m["omega"] * t) + m["b"] * np.sin(m["omega"] * t))
        return y


def _taylor(c, p, n):
    """First n coefficients of the polynomial c (highest power first) written in powers of (s - p)."""
    c = np.asarray(c, complex)
    out = []
    for _ in range(n):
        if len(c) == 0:
            out.append(0j)
            continue
        q, r = np.polydiv(c, np.array([1.0, -p]))
        out.append(complex(r[0]) if len(r) else 0j)
        c = q
    return out


def _partial_fractions(num, groups):
    """num / prod (s - p)^m over the distinct poles `groups` [(p, m)], num of lower degree -> {(p, k): c} for c / (s - p)^k."""
    res = {}
    for p, m in groups:
        others = np.ones(1, complex)
        for q, mq in groups:
            if q is not p:
                for _ in range(mq):
                    others = np.polymul(others, np.array([1.0, -q]))
        nt, dt = _taylor(num, p, m), _taylor(others, p, m)
        h = []
        for k in range(m):
            h.append((nt[k] - sum(h[i] * dt[k - i] for i in range(k))) / dt[0])
        for j in range(m):
            res[(p, m - j)] = h[j]
    return res


def _exp_text(sigma):
    if abs(sigma) < 1e-12:
        return ""
    a = fmt(sigma)
    return "e^(" + ("-t" if a == "-1" else "t" if a == "1" else f"{a}t") + ")"


def _tpow(n):
    return "" if n == 0 else ("t" if n == 1 else f"t{SUP.get(n, '^' + str(n))}")


def _term_parts(m):
    """(sign, text) of one term of y(t)."""
    ex, tp = _exp_text(m["sigma"]), _tpow(m["n"])
    scale = 1.0 / math.factorial(m["n"]) if m["n"] else 1.0
    if m["kind"] == "real":
        c = m["c"]
        mag = fmt(abs(c))
        sign = "-" if c < 0 else "+"
        lead = [x for x in (tp, ex) if x]
        if not lead:
            return sign, mag
        body = "·".join(lead)
        return sign, (body if mag == "1" else mag + body)
    a, b = m["a"], m["b"]
    wt = fmt(m["omega"])
    wt = "" if wt == "1" else wt
    cos_, sin_ = f"cos({wt}t)", f"sin({wt}t)"
    lead = "·".join(x for x in (tp, ex) if x)

    def one(coef, trig):
        mag = fmt(abs(coef))
        return (trig if mag == "1" else mag + trig)

    if abs(a) > 1e-12 and abs(b) > 1e-12:                    # a cos + b sin: the sign of a goes in front, the rest inside the bracket
        inner = one(a, cos_) + (" - " if (b < 0) != (a < 0) else " + ") + one(b, sin_)
        return ("-" if a < 0 else "+"), (lead + "(" + inner + ")")
    coef, trig = (a, cos_) if abs(a) > 1e-12 else (b, sin_)
    mag = fmt(abs(coef))
    return ("-" if coef < 0 else "+"), ("" if mag == "1" else mag) + lead + trig


def _delta_text(k):
    return "δ(t)" if k == 0 else ("δ'(t)" if k == 1 else f"δ({k})(t)")


def _y_text(terms, deltas):
    pieces = []
    for k in sorted(deltas):
        c = deltas[k]
        pieces.append(("-" if c < 0 else "+", ("" if abs(abs(c) - 1) < 1e-12 else fmt(abs(c))) + _delta_text(k)))
    for m in terms:
        pieces.append(_term_parts(m))
    if not pieces:
        return "0"
    out = ""
    for i, (sg, body) in enumerate(pieces):
        out += (("-" if sg == "-" else "") if i == 0 else f" {sg} ") + body
    return out


def _pf_text(res, groups):
    """Y(s) in partial fractions as text."""
    pieces = []
    done = set()
    for p, m in sorted(groups, key=lambda g: (-round(g[0].real, 9), -g[0].imag)):
        if (p.imag > 1e-9):
            if p in done:
                continue
            done.add(p)
            for k in range(1, m + 1):
                c = res[(p, k)]
                if k == 1:
                    A, B, sg, om = c.real, c.imag, p.real, p.imag
                    num = poly_text([2 * A, -2 * (A * sg + B * om)])
                    den = poly_text([1, -2 * sg, sg * sg + om * om])
                    pieces.append(("+", (f"({num})" if "s" in num else num) + f" / ({den})"))
                else:
                    pieces.append(("+", f"[{cfmt(c)} / (s - ({cfmt(p)})){SUP.get(k, '^' + str(k))} + conjugate]"))
        elif p.imag < -1e-9:
            continue
        else:
            for k in range(1, m + 1):
                c = res[(p, k)].real
                if abs(c) < 1e-12:
                    continue
                base = "s" if abs(p.real) < 1e-12 else f"(s {'+' if -p.real > 0 else '-'} {fmt(abs(p.real))})"
                den = base + ("" if k == 1 else SUP.get(k, f"^{k}"))
                pieces.append(("-" if c < 0 else "+", f"{fmt(abs(c))} / {den}"))
    if not pieces:
        return "0"
    out = ""
    for i, (sg, body) in enumerate(pieces):
        out += (("-" if sg == "-" else "") if i == 0 else f" {sg} ") + body
    return out


def _reduced(a):
    """K, zeros, poles with every cancelling pole / zero pair removed."""
    zs = list(a.zeros)
    ps = []
    for p in a.poles:
        for k, z in enumerate(zs):
            if abs(p - z) <= REL * 10 * max(1.0, abs(p)):
                del zs[k]
                break
        else:
            ps.append(p)
    return a.gain, zs, ps


def response_of(a, kind):
    """time_response, remembered on the Analysis."""
    cache = a.__dict__.setdefault("_responses", {})
    if kind not in cache:
        cache[kind] = time_response(a, kind)
    return cache[kind]


def time_response(a, kind):
    """Analytical unit step ('step') or unit impulse ('impulse') response of the Analysis `a`."""
    K, zs, ps = _reduced(a)
    num = K * np.real(np.poly(zs)) if zs else np.array([K])
    pole_list = list(ps) + ([complex(0, 0)] if kind == "step" else [])
    groups = []
    for r in sorted(pole_list, key=lambda z: (-round(z.real, 9), -z.imag)):
        for k, (q, m) in enumerate(groups):
            if abs(r - q) <= 1e-4 * max(1.0, abs(q)):
                groups[k] = ((q * m + r) / (m + 1), m + 1)
                break
        else:
            groups.append((r, 1))
    groups = [(complex(q.real, 0.0) if abs(q.imag) < 1e-9 * max(1.0, abs(q)) else q, m) for q, m in groups]
    den = np.ones(1, complex)
    for q, m in groups:
        for _ in range(m):
            den = np.polymul(den, np.array([1.0, -q]))
    den = np.real(den) if np.allclose(den.imag, 0, atol=1e-9 * max(1.0, float(np.max(np.abs(den))))) else den
    deltas = {}
    rem = np.asarray(num, complex)
    if len(num) >= len(den):
        quo, rem = np.polydiv(np.asarray(num, complex), np.asarray(den, complex))
        for i, qc in enumerate(quo[::-1]):                    # coefficient of s^i is the i-th derivative of delta
            if abs(qc) > 1e-12 * max(1.0, abs(K)):
                deltas[i] = float(qc.real)
    res = _partial_fractions(rem, groups) if groups and np.any(np.abs(rem) > 0) else {}
    terms = []
    for (p, k), c in res.items():
        if abs(c) < 1e-12 * max(1.0, abs(K)):
            continue
        if p.imag > 1e-9:
            terms.append({"kind": "osc", "n": k - 1, "sigma": p.real, "omega": p.imag, "a": 2 * c.real, "b": -2 * c.imag})
        elif p.imag < -1e-9:
            continue
        else:
            terms.append({"kind": "real", "n": k - 1, "sigma": p.real if abs(p.real) > 1e-12 else 0.0, "omega": 0.0, "c": c.real})
    for m in terms:
        if m["kind"] == "osc" and abs(m["sigma"]) < 1e-12:
            m["sigma"] = 0.0
    terms.sort(key=lambda m: (0 if m["sigma"] == 0 and m["n"] == 0 else 1 if m["sigma"] == 0 else 2, -m["sigma"], m["n"], m["kind"] != "real"))
    r = Response()
    r.kind, r.terms, r.deltas = kind, terms, deltas
    r.text = _y_text(terms, deltas)
    pf = _pf_text(res, groups) if res else ""
    if deltas:                                            # an improper Y(s): a polynomial in s comes out first (each s^k is a derivative of delta)
        poly = poly_text([deltas.get(k, 0.0) for k in range(max(deltas), -1, -1)])
        pf = poly + ((" - " + pf[1:] if pf.startswith("-") else " + " + pf) if pf else "")
    r.pf_text = pf or "0"
    r.y0 = float(sum((m["c"] if m["kind"] == "real" else m["a"]) for m in terms if m["n"] == 0))
    # final value
    growing = [m for m in terms if m["sigma"] > 1e-9]
    marginal = [m for m in terms if abs(m["sigma"]) <= 1e-9]
    r.final, r.final_note = 0.0, "0"
    if growing:
        r.final, r.final_note = None, "grows without limit"
    elif any(m["n"] > 0 or m["kind"] == "osc" for m in marginal):
        r.final, r.final_note = None, ("grows without limit" if any(m["n"] > 0 for m in marginal) else "oscillates forever (no final value)")
    elif marginal:
        r.final = float(sum(m["c"] for m in marginal))
        r.final_note = fmt(r.final)
    # a time range that shows the whole story
    dec = [-m["sigma"] for m in terms if m["sigma"] < -1e-9]
    osc = [m["omega"] for m in terms if m["kind"] == "osc"]
    if growing:
        g = max(m["sigma"] for m in growing)
        t = 7.0 / g
    elif dec:
        t = 5.0 / min(dec)
        if any(abs(m["sigma"]) <= 1e-9 for m in terms if m["kind"] == "osc"):
            t = max(t, 6 * 2 * math.pi / min(w for w in osc))
    elif osc:
        t = 6 * 2 * math.pi / min(osc)
    else:
        t = 5.0
    if any(m["n"] > 0 and m["sigma"] == 0 for m in terms) or (kind == "step" and r.final is None and not growing and not osc):
        t = max(t, 5.0) if not dec else t
    if r.final is None and not growing and dec and not osc:      # a ramp: show the transient and then the straight line it settles to
        t *= 8
    r.horizon = float(min(max(t, 1e-3), 1e4))
    return r


# ------------------------------------------------------------------------------------------------------------- Routh-Hurwitz
from fractions import Fraction  # noqa: E402


class Routh:
    """rows: [{'power': n, 'cells': [text], 'values': [float], 'kind': 'normal'|'eps'|'aux_source'|'aux_derivative'}]; first_col: [float];
    changes; rhp; imag (roots on the imaginary axis found); verdict; necessary (ok, text); notes; aux (list of (text, roots)); check (text)."""


def _sgn(x):
    return (x > 0) - (x < 0)


def _build_routh(a, eps):
    """The array for polynomial coefficients a (Fractions, highest first, a[0] > 0, no trailing zero) using a number for epsilon."""
    n = len(a) - 1
    width = n // 2 + 1
    r0 = [a[j] for j in range(0, n + 1, 2)]
    r1 = [a[j] for j in range(1, n + 1, 2)]
    r0 += [Fraction(0)] * (width - len(r0))
    r1 += [Fraction(0)] * (width - len(r1))
    rows = [r0, r1]
    kinds = ["normal", "normal"]
    aux = []
    for i in range(2, n + 1):
        prev2, prev = rows[i - 2], rows[i - 1]
        if all(x == 0 for x in prev):                                   # a whole row of zeros: build the auxiliary equation from the row above
            p2 = n - (i - 2)
            coeffs = [Fraction(0)] * (p2 + 1)
            for j, x in enumerate(prev2):
                q = p2 - 2 * j
                if q >= 0:
                    coeffs[p2 - q] = x
            aux.append((p2, coeffs))
            prev = [Fraction(p2 - 2 * j) * x if p2 - 2 * j > 0 else Fraction(0) for j, x in enumerate(prev2)]
            rows[i - 1] = prev
            kinds[i - 2] = "aux_source"
            kinds[i - 1] = "aux_derivative"
        piv = prev[0]
        if piv == 0:                                                     # a zero alone in the first column: a small epsilon takes its place
            prev = [eps] + prev[1:]
            rows[i - 1] = prev
            kinds[i - 1] = "eps"
            piv = eps
        new = [(piv * prev2[j + 1] - prev2[0] * prev[j + 1]) / piv for j in range(width - 1)] + [Fraction(0)]
        rows.append(new)
        kinds.append("normal")
    return rows, kinds, aux


def routh(den):
    """Routh array and verdict for the characteristic polynomial `den` (coefficients, highest power first).  Raises TFError if there is no s."""
    a = [Fraction(float(c)).limit_denominator(10 ** 9) for c in trim(den)]
    while a and a[0] == 0:
        a.pop(0)
    if len(a) < 2:
        raise TFError("The characteristic polynomial has no s in it, so there is nothing to test.")
    notes = []
    if a[0] < 0:
        a = [-c for c in a]
        notes.append("The leading coefficient was negative; every coefficient was multiplied by -1 (the roots do not change).")
    origin = 0
    while a[-1] == 0:                                                    # roots at s = 0
        a.pop()
        origin += 1
    full = [float(c) for c in a] + [0.0] * origin
    if origin:
        notes.append("%s s = 0 is a root%s; it is taken out and the rest is tested." % ("The factor s^%d: " % origin if origin > 1 else "A factor s:", " (repeated)" if origin > 1 else ""))
    n = len(a) - 1
    # necessary condition
    allc = [Fraction(float(c)).limit_denominator(10 ** 9) for c in trim(den)]
    if allc and allc[0] < 0:
        allc = [-c for c in allc]
    missing = [len(allc) - 1 - i for i, c in enumerate(allc) if c == 0]
    negative = [len(allc) - 1 - i for i, c in enumerate(allc) if c < 0]
    r = Routh()
    if missing:
        r.necessary = (False, "Necessary condition fails: the s^%s term%s missing (every power of s must be present)." % (", s^".join(str(m) for m in missing), " is" if len(missing) == 1 else "s are"))
    elif negative:
        r.necessary = (False, "Necessary condition fails: some coefficients are negative (all must have the same sign).")
    else:
        r.necessary = (True, "Necessary condition holds: all powers of s are present and all coefficients are positive.")
    if n == 0:
        r.rows, r.first_col, r.changes, r.rhp, r.imag, r.aux, r.notes = [], [], 0, 0, 0, [], notes
        r.verdict = "Marginally stable (only roots at s = 0)"
        r.check = ""
        return r
    e1, e2 = Fraction(1, 10 ** 6), Fraction(1, 10 ** 7)
    rows1, kinds, aux = _build_routh(a, e1)
    rows2, _k, _a = _build_routh(a, e2)
    out = []
    for i, (row, row2) in enumerate(zip(rows1, rows2)):
        cells = []
        for x, y in zip(row, row2):
            x, y = float(x), float(y)
            if kinds[i] == "eps" and cells == [] and x == float(e1):
                cells.append("ε")
            elif abs(x - y) > 1e-9 * max(1.0, abs(x)) and x != 0 and y != 0:        # depends on epsilon: show the leading term c·ε^p
                p = round(math.log10(abs(x / y)))
                c = x / float(e1) ** p
                cells.append(("%sε" % fmt(c) if p == 1 else "%s/ε" % fmt(c) if p == -1 else "%sε^%d" % (fmt(c), p)).replace("1ε", "ε").replace("-1ε", "-ε"))
            else:
                cells.append(fmt(x))
        out.append({"power": n - i, "cells": cells, "values": [float(x) for x in row], "kind": kinds[i]})
    # a row's last (padding) zeros are not part of the table
    for i, row in enumerate(out):
        used = (n - i) // 2 + 1 if i >= 2 else (len(a[(i)::2]))
        row["cells"] = row["cells"][:max(1, used if i >= 2 else len(a[i::2]))]
        row["values"] = row["values"][:len(row["cells"])]
    first = [float(rw[0]) for rw in rows1]
    r.rows = out
    r.first_col = first
    signs = [_sgn(x) for x in first if x != 0]
    r.changes = sum(1 for x, y in zip(signs, signs[1:]) if x != y)
    r.aux = []
    imag_aux = 0
    for p2, coeffs in aux:
        cf = [float(c) for c in coeffs]
        roots = np.roots(cf) if p2 >= 1 else np.array([])
        text = poly_text(cf)
        r.aux.append((text, list(roots)))
        imag_aux += int(sum(1 for z in roots if abs(z.real) <= 1e-7 * max(1.0, abs(z))))
        notes.append("A row of zeros appeared. The auxiliary equation (from the row above it) is %s = 0, with roots %s." % (text, ", ".join(cfmt(z) for z in roots)))
        notes.append("Its derivative's coefficients replace the row of zeros, and the array is finished.")
    if any(k == "eps" for k in kinds):
        notes.append("A zero alone in the first column was replaced by a small ε > 0, and the signs are read as ε → 0.")
    r.imag = imag_aux + origin
    r.rhp = r.changes
    if r.rhp:
        r.verdict = "Unstable: %d sign change%s in the first column, so %d pole%s in the right half-plane" % (r.changes, "" if r.changes == 1 else "s", r.rhp, "" if r.rhp == 1 else "s")
    elif r.imag:
        r.verdict = "Marginally stable: no sign changes, but %d root%s on the imaginary axis (simple roots; repeated ones would make it unstable)" % (r.imag, "" if r.imag == 1 else "s")
    else:
        r.verdict = "Stable: no sign changes in the first column, so no poles in the right half-plane"
    r.notes = notes
    # cross-check with the real roots
    roots = np.roots(full)
    tol = 1e-6
    rhp_n = int(sum(1 for z in roots if z.real > tol * max(1.0, abs(z))))
    axis_n = int(sum(1 for z in roots if abs(z.real) <= tol * max(1.0, abs(z))))
    r.rhp_roots, r.axis_roots = rhp_n, axis_n
    r.check = ("Check with the roots: %d in the right half-plane, %d on the imaginary axis%s" %
               (rhp_n, axis_n, " (agrees)." if rhp_n == r.rhp else " - DISAGREES with the array; the array is exact, so trust it only if the polynomial has repeated roots on the axis."))
    return r
