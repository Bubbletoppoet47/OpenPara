"""ctl_circuit.py - drawn networks to transfer functions (no Qt).

A network is a list of parts, each a dict {"kind", "a": (x, y), "b": (x, y) or None, "name", "value", "rot"}.  Parts that share a grid point (or whose
terminal lies on a wire) share a node.

  Electrical:  V (source, a = +, b = -), R, L, C, W (wire), GND (one terminal), VO (output probe, one terminal)
  Mechanical:  M (mass, both ends are the same body), K (spring), B (damper), WALL (one terminal), F (applied force), X (output probe)

The solver is modified nodal analysis in the s domain with exact polynomial arithmetic in s and in the part names, so the answer comes out
symbolically (1 / (L C s^2 + R C s + 1)) and, with numbers filled in, as a plain transfer function.  Mechanical systems use the force-current
analogy (mass = capacitor to ground, spring = inductor, damper = resistor, force = current source, velocity = node voltage), and the output
displacement is the velocity divided by s.
"""
import re
from fractions import Fraction

import ctl_core as core

ELECTRICAL = ("V", "R", "L", "C", "W", "GND", "VO")
MECHANICAL = ("M", "K", "B", "WALL", "F", "X")
TWO = ("V", "R", "L", "C", "W", "M", "K", "B")             # parts with two terminals
VALUED = ("R", "L", "C", "M", "K", "B")                    # parts that carry a value
MAX_UNKNOWNS = 22


class CircuitError(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------- polynomials in s and the part names
class Poly:
    """Multivariate polynomial with exact (Fraction) coefficients.  terms: {((name, power), ...) sorted: coefficient}."""
    __slots__ = ("t",)

    def __init__(self, t=None):
        self.t = {k: v for k, v in (t or {}).items() if v != 0}

    @staticmethod
    def const(c):
        return Poly({(): Fraction(c)})

    @staticmethod
    def sym(name, power=1):
        return Poly({((name, power),): Fraction(1)})

    def __bool__(self):
        return bool(self.t)

    def __neg__(self):
        return Poly({k: -v for k, v in self.t.items()})

    def __add__(self, o):
        r = dict(self.t)
        for k, v in o.t.items():
            r[k] = r.get(k, 0) + v
        return Poly(r)

    def __sub__(self, o):
        return self + (-o)

    def __mul__(self, o):
        r = {}
        for k1, v1 in self.t.items():
            for k2, v2 in o.t.items():
                k = _mono_mul(k1, k2)
                r[k] = r.get(k, 0) + v1 * v2
        return Poly(r)

    def subs(self, values):
        """Replace names that have a numeric value (a dict name -> Fraction)."""
        r = Poly()
        for k, v in self.t.items():
            c, rest = v, []
            for name, p in k:
                if name in values:
                    c = c * values[name] ** p
                else:
                    rest.append((name, p))
            r = r + Poly({tuple(rest): c})
        return r

    def names(self):
        return {n for k in self.t for n, _p in k if n != "s"}

    def by_s(self):
        """{power of s: Poly in the other names}."""
        out = {}
        for k, v in self.t.items():
            p = 0
            rest = []
            for n, e in k:
                if n == "s":
                    p = e
                else:
                    rest.append((n, e))
            out.setdefault(p, {})[tuple(rest)] = v
        return {p: Poly(d) for p, d in out.items()}

    def coeffs(self):
        """Plain numbers: [c_n ... c_0] in s (highest first) when only s is left, else None."""
        if self.names():
            return None
        d = self.by_s()
        if not d:
            return [0.0]
        n = max(d)
        return [float(d[p].t.get((), 0)) if p in d else 0.0 for p in range(n, -1, -1)]


def _mono_mul(a, b):
    d = dict(a)
    for n, p in b:
        d[n] = d.get(n, 0) + p
    return tuple(sorted(d.items()))


def det(m):
    """Determinant of a square matrix of Poly (None = 0) by expansion with memoisation over the columns still free."""
    n = len(m)
    if n == 0:
        return Poly.const(1)
    order = sorted(range(n), key=lambda r: sum(1 for x in m[r] if x))          # sparse rows first keeps the expansion small
    rows = [m[r] for r in order]
    sign0 = _perm_sign(order)
    memo = {}

    def f(r, mask):
        if r == n:
            return Poly.const(1)
        key = (r, mask)
        if key in memo:
            return memo[key]
        total = Poly()
        idx = 0
        for c in range(n):
            if not (mask >> c) & 1:
                continue
            x = rows[r][c]
            if x:
                sub = f(r + 1, mask & ~(1 << c))
                if sub:
                    term = x * sub
                    total = total + (term if idx % 2 == 0 else -term)
            idx += 1
        memo[key] = total
        return total

    d = f(0, (1 << n) - 1)
    return d if sign0 > 0 else -d


def _perm_sign(p):
    p = list(p)
    s = 1
    seen = [False] * len(p)
    for i in range(len(p)):
        if not seen[i]:
            j, ln = i, 0
            while not seen[j]:
                seen[j] = True
                j = p[j]
                ln += 1
            if ln % 2 == 0:
                s = -s
    return s


# ------------------------------------------------------------------------------------------------------------- values and names
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def parse_value(text):
    """'0.05' -> Fraction(1, 20);  '' or a name -> None."""
    t = str(text or "").strip()
    if not t:
        return None
    try:
        return Fraction(t)
    except (ValueError, ZeroDivisionError):
        return None


def default_name(kind, parts):
    base = {"V": "Vi", "VO": "Vo", "X": "x"}.get(kind, kind)
    same = sum(1 for p in parts if p["kind"] == kind)
    return base if same == 0 else "%s%d" % (base, same + 1)


# ------------------------------------------------------------------------------------------------------------- netlist
class Net:
    """The nodes and elements found in a list of parts."""

    def __init__(self, parts, domain):
        self.domain = domain
        kinds = ELECTRICAL if domain == "electrical" else MECHANICAL + ("W",)
        ps = [p for p in parts if p["kind"] in kinds]
        self.parts = ps
        par = {}

        def find(x):
            par.setdefault(x, x)
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        def union(x, y):
            par[find(x)] = find(y)

        pts = []
        for p in ps:
            for k in ("a", "b"):
                if p.get(k) is not None:
                    pts.append(tuple(p[k]))
                    find(tuple(p[k]))
        for p in ps:
            if p["kind"] == "W":
                union(tuple(p["a"]), tuple(p["b"]))
                for q in pts:                                          # a terminal that lands on a wire joins it
                    if _on_segment(q, tuple(p["a"]), tuple(p["b"])):
                        union(q, tuple(p["a"]))
            elif p["kind"] == "M":
                union(tuple(p["a"]), tuple(p["b"]))                    # a mass is one rigid body
        ground = [tuple(p["a"]) for p in ps if p["kind"] in ("GND", "WALL")]
        if not ground:
            raise CircuitError("Add a ground symbol (the 0 V reference)." if domain == "electrical"
                               else "Add a wall (the fixed reference) and connect the spring and damper to it.")
        for g in ground[1:]:
            union(g, ground[0])
        self.find = find
        self.ground = find(ground[0])
        self.elements = []                                              # (kind, part, node_a, node_b)
        self.source = None
        self.probe = None
        for p in ps:
            k = p["kind"]
            if k in ("R", "L", "C", "K", "B"):
                self.elements.append((k, p, find(tuple(p["a"])), find(tuple(p["b"]))))
            elif k == "V":
                if self.source:
                    raise CircuitError("Only one voltage source can be the input.")
                self.source = (k, p, find(tuple(p["a"])), find(tuple(p["b"])))
            elif k == "M":
                self.elements.append(("M", p, find(tuple(p["a"])), self.ground))
            elif k == "F":
                if self.source:
                    raise CircuitError("Only one applied force can be the input.")
                self.source = (k, p, self.ground, find(tuple(p["a"])))
            elif k in ("VO", "X"):
                if self.probe:
                    raise CircuitError("Only one output probe is allowed.")
                self.probe = find(tuple(p["a"]))
        if not self.source:
            raise CircuitError("Add a voltage source Vi as the input." if domain == "electrical" else "Add an applied force F as the input.")
        if self.probe is None:
            raise CircuitError("Add an output probe Vo on the node you want to measure." if domain == "electrical"
                               else "Add an output probe x on the mass whose displacement you want.")


def _on_segment(q, a, b):
    if q == a or q == b:
        return False
    (x, y), (x1, y1), (x2, y2) = q, a, b
    if (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) != 0:
        return False
    return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)


def sym_name(p):
    """The name a part stands for when it has no number: what is typed in Value, else its Name."""
    v = str(p.get("value") or "").strip()
    return v if v and parse_value(v) is None else (p.get("name") or "").strip()


def symbol_of(p):
    """The number a part contributes if it has one, else its name."""
    v = parse_value(p.get("value"))
    return ("num", v) if v is not None else ("sym", sym_name(p))


def _poly_of(p, bad):
    kind, val = symbol_of(p)
    if kind == "num":
        if val <= 0:
            bad.append("%s must be positive." % (p.get("name") or p["kind"]))
        return Poly.const(val)
    if not _NAME.match(val) or val == "s":
        bad.append("'%s' is not a usable name (letters and digits, not s)." % val if val else "Every part needs a name or a number.")
        return Poly.const(1)
    return Poly.sym(val)


class Solution:
    """num, den: Poly (in s and the part names); domain; in_name / out_name for the text."""
    pass


def solve(parts, domain):
    """Transfer function of a drawn network: returns a Solution; raises CircuitError with a plain-words reason."""
    net = Net(parts, domain)
    bad = []
    nodes = []
    for _k, _p, a, b in net.elements + [net.source]:
        for n in (a, b):
            if n != net.ground and n not in nodes:
                nodes.append(n)
    if net.probe != net.ground and net.probe not in nodes:
        raise CircuitError("The output probe is not connected to the network.")
    if net.probe == net.ground:
        raise CircuitError("The output probe is on the ground node (it would always read 0).")
    elems = net.elements + [net.source]
    N, B = len(nodes), len(elems)
    n = N + B
    if n > MAX_UNKNOWNS:
        raise CircuitError("This network is too large for the symbolic solver yet (%d unknowns)." % n)
    col = {nd: i for i, nd in enumerate(nodes)}
    M = [[None] * n for _ in range(n)]
    rhs = [Poly() for _ in range(n)]
    S, ONE = Poly.sym("s"), Poly.const(1)

    def add(r, c, v):
        M[r][c] = v if M[r][c] is None else M[r][c] + v

    for e, (k, p, a, b) in enumerate(elems):
        i = N + e                                                      # this element's current (or force) column and its own row
        if a != net.ground:
            add(col[a], i, ONE)                                        # KCL: current leaves node a ...
        if b != net.ground:
            add(col[b], i, -ONE)                                       # ... and arrives at node b
        va = (lambda x: add(i, col[a], x)) if a != net.ground else (lambda x: None)
        vb = (lambda x: add(i, col[b], x)) if b != net.ground else (lambda x: None)
        if k == "V":
            va(ONE)
            vb(-ONE)
            rhs[i] = ONE
        elif k == "F":
            add(i, i, ONE)
            rhs[i] = ONE
        else:
            val = _poly_of(p, bad)
            if k == "R":
                va(ONE), vb(-ONE), add(i, i, -val)
            elif k == "L":
                va(ONE), vb(-ONE), add(i, i, -(S * val))
            elif k == "C":
                add(i, i, ONE), va(-(S * val)), vb(S * val)
            elif k == "K":
                va(val), vb(-val), add(i, i, -S)
            elif k == "B":
                add(i, i, ONE), va(-val), vb(val)
            elif k == "M":
                add(i, i, ONE), va(-(S * val))
    if bad:
        raise CircuitError(bad[0])
    D = det(M)
    if not D:
        raise CircuitError("The network cannot be solved: check that every part is wired in and that the ground symbol touches the circuit.")
    j = col[net.probe]
    A = [row[:] for row in M]
    for r in range(n):
        A[r][j] = rhs[r] if rhs[r] else None
    Nu = det(A)
    if not Nu:
        raise CircuitError("The input does not reach the output: the output is always 0. Check the wiring.")
    if domain == "mechanical":
        D = D * S                                                      # displacement = velocity / s
    sol = Solution()
    sol.num, sol.den = _tidy(Nu, D)
    sol.domain = domain
    sol.in_name, sol.out_name = ("Vi", "Vo") if domain == "electrical" else ("F", "x")
    sol.net = net
    return sol


def _tidy(n, d):
    """Drop a common monomial factor and fix the sign so the highest power of s in the denominator is positive."""
    common = None
    for k in list(n.t) + list(d.t):
        dk = dict(k)
        common = dk if common is None else {x: min(common[x], dk[x]) for x in common if x in dk}
    if common:
        c = tuple(sorted((x, p) for x, p in common.items() if p > 0))
        if c:
            n = Poly({_mono_div(k, c): v for k, v in n.t.items()})
            d = Poly({_mono_div(k, c): v for k, v in d.t.items()})
    top = d.by_s()
    lead = top[max(top)]
    first = lead.t[sorted(lead.t)[0]]
    if first < 0:
        n, d = -n, -d
        top = d.by_s()
    # scale: monic in s when the highest coefficient is a plain number (1 / (s² + B s + 2)), else make the constant term 1 when that is a plain number
    for pick in (max(top), min(top)):
        c = top[pick]
        if set(c.t) == {()}:
            k = c.t[()]
            if k != 1:
                n = Poly({kk: v / k for kk, v in n.t.items()})
                d = Poly({kk: v / k for kk, v in d.t.items()})
            break
    return n, d


def _mono_div(k, c):
    d = dict(k)
    for x, p in c:
        d[x] -= p
    return tuple(sorted((x, p) for x, p in d.items() if p))


# ------------------------------------------------------------------------------------------------------------- text
_SUP = {2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹"}


def _pow(p):
    return _SUP.get(p, "^%d" % p) if p > 1 else ""


def _num(x):
    return core.fmt(float(x), 6)


def _mono(k, coef, power_s):
    """One term: coefficient, names, then s^power."""
    parts = ["%s%s" % (n, _pow(p)) for n, p in k]
    if power_s:
        parts.append("s" + _pow(power_s))
    body = " ".join(parts)
    c = abs(coef)
    if not body:
        return _num(c)
    return body if c == 1 else _num(c) + " " + body


def poly_text(P):
    """Polynomial in s with named coefficients: 'L C s² + R C s + 1';  '(R1 + R2) s + 1' when one power of s has several terms."""
    d = P.by_s()
    if not d:
        return "0"
    out = []
    for p in sorted(d, reverse=True):
        c = d[p]
        ks = sorted(c.t, key=lambda k: (-len(k), k))
        if len(ks) == 1:
            k = ks[0]
            neg = c.t[k] < 0
            out.append((neg, _mono(k, c.t[k], p)))
        else:
            inner = ""
            for i, k in enumerate(ks):
                v = c.t[k]
                t = _mono(k, v, 0)
                inner += (("- " if v < 0 else "") + t) if i == 0 else (" - " if v < 0 else " + ") + t
            out.append((False, "(" + inner + ")" + (" s" + _pow(p) if p else "")))
    text = ""
    for i, (neg, t) in enumerate(out):
        text += (("-" if neg else "") + t) if i == 0 else (" - " if neg else " + ") + t
    return text


def _is_sum(text):
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and text[i:i + 3] in (" + ", " - "):
            return True
    return False


def _wrapped(text):
    """True when one pair of brackets already encloses the whole text."""
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(text) - 1:
            return False
    return True


def tf_text(sol, num=None, den=None):
    """'1 / (L C s² + R C s + 1)'."""
    n = poly_text(num if num is not None else sol.num)
    d = poly_text(den if den is not None else sol.den)
    if _is_sum(n) and not _wrapped(n):
        n = "(" + n + ")"
    if (_is_sum(d) or " " in d) and not _wrapped(d):
        d = "(" + d + ")"
    return "%s / %s" % (n, d)


def equation_text(sol):
    """D(s) Y = N(s) U as a differential equation, e.g. 'L C vo'' + R C vo' + vo = vi'."""
    y = "vo" if sol.domain == "electrical" else "x"
    u = "vi" if sol.domain == "electrical" else "F"

    def side(P, v):
        d = P.by_s()
        out = []
        for p in sorted(d, reverse=True):
            c = poly_text(d[p]) if d[p] else "0"
            deriv = v + "'" * p if p <= 3 else "d^%d%s/dt^%d" % (p, v, p)
            multi = len(d[p].t) > 1
            coef = "(" + c + ")" if multi else c
            out.append(deriv if c == "1" else coef + " " + deriv)
        return " + ".join(out).replace("+ -", "- ")
    return "%s = %s" % (side(sol.den, y), side(sol.num, u))


def numeric(sol, values):
    """With every name given a number: (num, den) coefficient lists, else None.  `values`: {name: Fraction}."""
    n, d = sol.num.subs(values), sol.den.subs(values)
    cn, cd = n.coeffs(), d.coeffs()
    return (cn, cd) if cn is not None and cd is not None else None


# ------------------------------------------------------------------------------------------------------------- analogies
def is_series_loop(parts):
    """True when the electrical network is one loop: a source and R, L, C in series."""
    try:
        net = Net(parts, "electrical")
    except CircuitError:
        return False
    els = net.elements + [net.source]
    if any(k not in ("R", "L", "C", "V") for k, *_ in els) or len(net.elements) < 1:
        return False
    deg = {}
    for _k, _p, a, b in els:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    if any(v != 2 for v in deg.values()):
        return False
    adj = {}
    for _k, _p, a, b in els:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    start = next(iter(adj))
    seen, todo = {start}, [start]
    while todo:
        x = todo.pop()
        for y in adj[x]:
            if y not in seen:
                seen.add(y)
                todo.append(y)
    return len(seen) == len(adj)


def is_single_body(parts):
    """True for one rigid body: masses, springs and dampers to the wall, one applied force."""
    try:
        net = Net(parts, "mechanical")
    except CircuitError:
        return False
    nodes = {a for _k, _p, a, b in net.elements for a in (a,)} | {net.source[3]}
    nodes.discard(net.ground)
    if len(nodes) != 1:
        return False
    for k, _p, a, b in net.elements:
        if k == "K" or k == "B":
            if {a, b} != {next(iter(nodes)), net.ground}:
                return False
    return any(k == "M" for k, *_ in net.elements)


def _label(p):
    return sym_name(p)


def _val(p):
    return parse_value(p.get("value"))


def _fnum(x):
    return core.fmt(float(x), 6)


def analog_of_loop(parts):
    """Series RLC loop -> (mechanical parts to draw, text lines).  Force-voltage analogy: L -> M, R -> B, C -> K = 1/C."""
    net = Net(parts, "electrical")
    Ls = [p for k, p, *_ in net.elements if k == "L"]
    Rs = [p for k, p, *_ in net.elements if k == "R"]
    Cs = [p for k, p, *_ in net.elements if k == "C"]
    lines = ["Force-voltage analogy (a series loop is one rigid body):"]
    mass_label, mass_names = [], []
    for p in Ls:
        v = _val(p)
        mass_names.append(_label(p))
        mass_label.append(_fnum(v) if v is not None else _label(p))
    out = []
    X0, X1, XM, XF = 2, 10, 14, 18                                     # wall bus, body bus, mass right end, force tip
    rows = []                                                         # (kind, label)
    for p in Cs:
        v = _val(p)
        rows.append(("K", "K = " + (_fnum(1 / v) if v is not None else "1/" + _label(p)), _label(p)))
    for p in Rs:
        v = _val(p)
        rows.append(("B", "B = " + (_fnum(v) if v is not None else _label(p)), _label(p)))
    ys = [3 + 4 * i for i in range(max(1, len(rows)))]
    mid = (ys[0] + ys[-1]) // 2
    out.append({"kind": "WALL", "a": (X0, mid), "b": None, "rot": 2, "name": "", "value": ""})
    out.append({"kind": "W", "a": (X0, ys[0]), "b": (X0, ys[-1]), "name": "", "value": ""})
    for y, (k, lab, _n) in zip(ys, rows):
        out.append({"kind": "W", "a": (X0, y), "b": (X0 + 1, y), "name": "", "value": ""})
        out.append({"kind": k, "a": (X0 + 1, y), "b": (X1 - 1, y), "name": "", "value": "", "label": lab})
        out.append({"kind": "W", "a": (X1 - 1, y), "b": (X1, y), "name": "", "value": ""})
    out.append({"kind": "W", "a": (X1, ys[0]), "b": (X1, ys[-1]), "name": "", "value": ""})
    mlab = "M = " + " + ".join(mass_label) if mass_label else "M"
    out.append({"kind": "M", "a": (X1, mid), "b": (XM, mid), "name": "", "value": "", "label": mlab})
    out.append({"kind": "F", "a": (XM, mid), "b": None, "rot": 0, "name": "F", "value": ""})
    for p in Ls:
        v = _val(p)
        lines.append("Inductor %s  ->  mass M = %s" % (_label(p), _fnum(v) if v is not None else _label(p)))
    for p in Rs:
        v = _val(p)
        lines.append("Resistor %s  ->  damper B = %s" % (_label(p), _fnum(v) if v is not None else _label(p)))
    for p in Cs:
        v = _val(p)
        lines.append("Capacitor %s  ->  spring K = %s" % (_label(p), _fnum(1 / v) if v is not None else "1/" + _label(p)))
    lines.append("Vi  ->  force F\ncurrent i  ->  velocity v\ncharge q  ->  displacement x")
    if Cs:
        lines.append("The voltage across C (q / C) matches the spring force K x.")
    lines.append("Equation:  M x'' + B x' + K x = F")
    return out, lines


def analog_of_body(parts):
    """One rigid body -> (electrical series loop to draw, text lines).  M -> L, B -> R, K -> C = 1/K."""
    net = Net(parts, "mechanical")
    Ms = [p for k, p, *_ in net.elements if k == "M"]
    Ks = [p for k, p, *_ in net.elements if k == "K"]
    Bs = [p for k, p, *_ in net.elements if k == "B"]
    lines = ["Force-voltage analogy (one rigid body is a series loop):"]
    items = []
    for p in Ms:
        v = _val(p)
        lab = "L = " + (_fnum(v) if v is not None else _label(p))
        items.append(("L", lab))
        lines.append("Mass %s  ->  inductor L = %s" % (_label(p), _fnum(v) if v is not None else _label(p)))
    for p in Bs:
        v = _val(p)
        lab = "R = " + (_fnum(v) if v is not None else _label(p))
        items.append(("R", lab))
        lines.append("Damper %s  ->  resistor R = %s" % (_label(p), _fnum(v) if v is not None else _label(p)))
    for p in Ks:
        v = _val(p)
        lab = "C = " + (_fnum(1 / v) if v is not None else "1/" + _label(p))
        items.append(("C", lab))
        lines.append("Spring %s  ->  capacitor C = %s" % (_label(p), _fnum(1 / v) if v is not None else "1/" + _label(p)))
    lines.append("Force F  ->  voltage source Vi\nvelocity v  ->  current i\ndisplacement x  ->  charge q")
    lines.append("Equation:  L q'' + R q' + q / C = Vi")
    out = []
    n = len(items)
    top, bot, x0 = 4, 10, 2
    xs = [x0 + 1 + 5 * i for i in range(n)]
    xr = xs[-1] + 5 if n else x0 + 6
    out.append({"kind": "V", "a": (x0, top), "b": (x0, bot), "name": "Vi", "value": ""})
    out.append({"kind": "W", "a": (x0, top), "b": (xs[0] if n else xr, top), "name": "", "value": ""})
    for i, (k, lab) in enumerate(items):
        a = xs[i]
        out.append({"kind": k, "a": (a, top), "b": (a + 4, top), "name": "", "value": "", "label": lab})
        if i + 1 < n:
            out.append({"kind": "W", "a": (a + 4, top), "b": (xs[i + 1], top), "name": "", "value": ""})
    out.append({"kind": "W", "a": ((xs[-1] + 4) if n else x0, top), "b": (xr, top), "name": "", "value": ""})
    out.append({"kind": "W", "a": (xr, top), "b": (xr, bot), "name": "", "value": ""})
    out.append({"kind": "W", "a": (x0, bot), "b": (xr, bot), "name": "", "value": ""})
    out.append({"kind": "GND", "a": ((x0 + xr) // 2, bot), "b": None, "rot": 1, "name": "", "value": ""})
    return out, lines


def analog_lines_general(parts, domain):
    """Correspondence lines for a network that is not a single loop / body."""
    if domain == "electrical":
        return ["Force-voltage analogy:", "L  ->  mass M = L;   R  ->  damper B = R;   C  ->  spring K = 1/C",
                "Vi  ->  force F;   current i  ->  velocity v;   charge q  ->  displacement x",
                "(A drawn mechanical analog is made for a single series loop; this network has branches.)"]
    return ["Force-current analogy (same wiring):", "Mass M  ->  capacitor to ground, C = M;   spring K  ->  inductor, L = 1/K;   damper B  ->  resistor, R = 1/B",
            "Force F  ->  current source;   velocity v  ->  node voltage;   wall  ->  ground",
            "(A drawn electrical analog is made for one rigid body; this system has several masses.)"]


# ------------------------------------------------------------------------------------------------------------- examples from the book
def _p(kind, a, b=None, name="", value="", rot=0):
    return {"kind": kind, "a": a, "b": b, "name": name, "value": value, "rot": rot}


def _wire(a, b):
    return _p("W", a, b)


EXAMPLES = (
    ("Book 1.5.5.3:  series R, L, C circuit", "electrical"),
    ("Book 1.5.5.2:  mass M=1, spring K=2, damper B", "mechanical"),
    ("Book 1.5.5.4:  two-port R1=5, R2=5, C=0.05, L=0.1", "electrical"),
)


def example(i):
    """(domain, parts) of example i."""
    if i == 0:
        return "electrical", [_p("V", (2, 4), (2, 10), "Vi"), _wire((2, 4), (4, 4)), _p("L", (4, 4), (8, 4), "L"), _p("R", (8, 4), (12, 4), "R"),
                              _wire((12, 4), (16, 4)), _p("C", (16, 4), (16, 10), "C"), _wire((2, 10), (16, 10)), _p("GND", (9, 10), None, rot=1),
                              _p("VO", (16, 4), None, "Vo", rot=0)]
    if i == 1:
        return "mechanical", [_p("WALL", (2, 6), None, rot=2), _wire((2, 3), (2, 9)), _p("K", (2, 3), (8, 3), "K", "2"), _p("B", (2, 9), (8, 9), "B"),
                              _wire((8, 3), (8, 9)), _p("M", (8, 6), (12, 6), "M", "1"), _p("F", (12, 6), None, "F", rot=0), _p("X", (12, 6), None, "x", rot=3)]
    return "electrical", [_p("V", (2, 4), (2, 10), "Vi"), _wire((2, 4), (4, 4)), _p("R", (4, 4), (8, 4), "R1", "5"), _p("L", (8, 4), (12, 4), "L", "0.1"),
                          _wire((12, 4), (20, 4)), _p("R", (16, 4), (16, 10), "R2", "5"), _p("C", (20, 4), (20, 10), "C", "0.05"), _wire((2, 10), (20, 10)),
                          _p("GND", (9, 10), None, rot=1), _p("VO", (20, 4), None, "Vo", rot=0)]
