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
    for m in a.modes:
        if m["kind"] == "pair":
            L.append(f"Poles {pair_text(m['pole'])}: wn = {fmt(m['wn'])} rad/s, zeta = {fmt(m['zeta'])}")
    if a.cancels:
        L.append("Pole and zero cancel at " + ", ".join(cfmt(c) for c in a.cancels))
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
