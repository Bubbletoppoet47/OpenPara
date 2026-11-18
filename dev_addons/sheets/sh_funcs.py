"""sh_funcs.py - the Excel functions of Sheets (about 120 of them) and CONVERT.  Importing this module adds them to sh_engine.FUNCS.

Each function is registered with a one-line summary and its arguments, which the Function Arguments window and the help line under the formula bar show.
Not here (and so #NAME?): OFFSET, INDIRECT, dates other than TODAY / NOW, financial and database functions.
"""
import datetime
import fnmatch
import math
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

import sh_fmt
from sh_engine import (_arith, DIV0, NA, NAME, NUM, REF, VALUE, Arr, Err, RefTok, elem, map_n, register, str_to_num, to_bool, to_num, to_text)


def reg(name, fn, summary, args=(), kind="scalar", ctx=False):
    args = [a if len(a) == 3 else (a[0], a[1], "") for a in args]
    lo = sum(1 for a in args if not a[2])
    hi = None if any(a[2] == "rep" for a in args) else len(args)
    register(name, fn, kind=kind, lo=lo, hi=hi, summary=summary, args=args, ctx=ctx)


def _x(name, hint, flag=""):
    return (name, hint, flag)


NUMBER = _x("number", "The number")


# ------------------------------------------------------------------------------------------------------------------ helpers
def _m1(f):
    """A one-number function: the argument is turned into a number, and a maths error becomes #NUM! / #DIV/0!."""
    def g(v):
        x = to_num(v)
        if isinstance(x, Err):
            return x
        try:
            r = f(x)
        except OverflowError:
            return NUM
        except ZeroDivisionError:
            return DIV0
        except ValueError:
            return NUM
        if isinstance(r, complex) or r != r or r in (math.inf, -math.inf):
            return NUM
        return r
    return g


def _collect(args):
    """(numbers, err): the numbers of the arguments (a range gives only its real numbers; a typed number, True / False or number-text counts too)."""
    out = []
    for a in args:
        if isinstance(a, Arr):
            for v in a.flat():
                if isinstance(v, Err):
                    return None, v
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
        else:
            if isinstance(a, Err):
                return None, a
            if isinstance(a, bool):
                out.append(1.0 if a else 0.0)
            elif isinstance(a, (int, float)):
                out.append(float(a))
            elif isinstance(a, str):
                n = str_to_num(a)
                if n is not None:
                    out.append(n)
    return out, None


def _agg(fn):
    def g(*args):
        xs, err = _collect(args)
        return err if err is not None else fn(xs)
    return g


def _flat(a):
    return list(a.flat()) if isinstance(a, Arr) else [a]


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _dec_round(x, nd, mode):
    try:
        q = Decimal(1).scaleb(-int(nd))
        r = Decimal(repr(float(x))).quantize(q, rounding=mode) if abs(nd) < 300 else Decimal(0)
        return float(r)
    except Exception:                                       # noqa: BLE001
        return NUM


def _round_to(mode):
    def f(x, nd=0.0):
        a, b = to_num(x), to_num(nd)
        if isinstance(a, Err):
            return a
        if isinstance(b, Err):
            return b
        nd_ = int(b)
        if nd_ < 0:                                         # to tens, hundreds ...
            q = Decimal(10) ** (-nd_)
            d = Decimal(repr(float(a))) / q
            return float(d.quantize(Decimal(1), rounding=mode) * q)
        return _dec_round(a, nd_, mode)
    return f


# ------------------------------------------------------------------------------------------------------------------ maths
for _n, _f, _s in (("ABS", abs, "The size of a number, without its sign"), ("SQRT", math.sqrt, "The square root"), ("EXP", math.exp, "e raised to a power"),
                   ("LN", math.log, "The natural logarithm"), ("LOG10", math.log10, "The base-10 logarithm"), ("SIN", math.sin, "Sine of an angle in radians"),
                   ("COS", math.cos, "Cosine of an angle in radians"), ("TAN", math.tan, "Tangent of an angle in radians"),
                   ("ASIN", math.asin, "Arcsine, in radians"), ("ACOS", math.acos, "Arccosine, in radians"), ("ATAN", math.atan, "Arctangent, in radians"),
                   ("SINH", math.sinh, "Hyperbolic sine"), ("COSH", math.cosh, "Hyperbolic cosine"), ("TANH", math.tanh, "Hyperbolic tangent"),
                   ("DEGREES", math.degrees, "Radians to degrees"), ("RADIANS", math.radians, "Degrees to radians"),
                   ("INT", lambda x: float(math.floor(x)), "Rounds down to the next whole number"),
                   ("SIGN", lambda x: float((x > 0) - (x < 0)), "1, 0 or -1: the sign of a number"),
                   ("FACT", lambda x: float(math.factorial(int(x))) if x >= 0 and x == int(x) else NUM, "The factorial of a whole number")):
    reg(_n, _m1(_f), _s, [("number", "The number" if _n not in ("SIN", "COS", "TAN") else "The angle in radians")])
reg("PI", lambda: math.pi, "The number pi, 3.14159...", [])
reg("POWER", lambda a, b: _arith("^", a, b), "A number raised to a power", [("number", "The base"), ("power", "The exponent")])


def _log(x, base=10.0):
    a, b = to_num(x), to_num(base)
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if a <= 0 or b <= 0 or b == 1:
        return NUM
    return math.log(a) / math.log(b)


reg("LOG", _log, "The logarithm of a number to a base (10 if left out)", [("number", "The number"), ("base", "The base; 10 if left out", "opt")])


def _mod(a, b):
    x, y = to_num(a), to_num(b)
    if isinstance(x, Err):
        return x
    if isinstance(y, Err):
        return y
    return DIV0 if y == 0 else x - y * math.floor(x / y)


reg("MOD", _mod, "The remainder after dividing (same sign as the divisor)", [("number", "The number to divide"), ("divisor", "The number to divide by")])
reg("ATAN2", lambda x, y: (lambda a, b: a if isinstance(a, Err) else b if isinstance(b, Err) else (DIV0 if a == 0 and b == 0 else math.atan2(b, a)))(to_num(x), to_num(y)),
    "The angle of the point (x, y), in radians", [("x_num", "x coordinate"), ("y_num", "y coordinate")])
reg("ROUND", _round_to(ROUND_HALF_UP), "Rounds to a number of decimals", [("number", "The number"), ("num_digits", "How many decimals (0 = whole number)")])
reg("ROUNDUP", _round_to(ROUND_UP), "Rounds away from zero", [("number", "The number"), ("num_digits", "How many decimals")])
reg("ROUNDDOWN", _round_to(ROUND_DOWN), "Rounds toward zero", [("number", "The number"), ("num_digits", "How many decimals")])
reg("TRUNC", lambda x, nd=0.0: _round_to(ROUND_DOWN)(x, nd), "Cuts a number to a number of decimals", [("number", "The number"), ("num_digits", "How many decimals", "opt")])


def _mult(up):
    def f(x, sig=1.0):
        a, s = to_num(x), to_num(sig)
        if isinstance(a, Err):
            return a
        if isinstance(s, Err):
            return s
        if s == 0:
            return 0.0
        if a * s < 0:
            return NUM
        return (math.ceil(a / s) if up else math.floor(a / s)) * s
    return f


reg("CEILING", _mult(True), "Rounds up to a multiple", [("number", "The number"), ("significance", "The multiple", "opt")])
reg("FLOOR", _mult(False), "Rounds down to a multiple", [("number", "The number"), ("significance", "The multiple", "opt")])
reg("MROUND", lambda x, m: (lambda a, b: a if isinstance(a, Err) else b if isinstance(b, Err) else 0.0 if b == 0 else (NUM if a * b < 0 else math.floor(a / b + 0.5) * b))(to_num(x), to_num(m)),
    "Rounds to the nearest multiple", [("number", "The number"), ("multiple", "The multiple")])
reg("ISEVEN", lambda v: (lambda x: x if isinstance(x, Err) else int(math.floor(x)) % 2 == 0)(to_num(v)), "True when a number is even", [NUMBER])
reg("ISODD", lambda v: (lambda x: x if isinstance(x, Err) else int(math.floor(x)) % 2 == 1)(to_num(v)), "True when a number is odd", [NUMBER])


# ------------------------------------------------------------------------------------------------------------------ sums, counts, statistics
reg("SUM", _agg(lambda xs: math.fsum(xs)), "Adds all the numbers", [("number1", "A number or a range"), ("number2", "More numbers or ranges", "rep")], kind="agg")
reg("PRODUCT", _agg(lambda xs: math.prod(xs) if xs else 0.0), "Multiplies all the numbers", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
reg("SUMSQ", _agg(lambda xs: math.fsum(x * x for x in xs)), "Sum of the squares", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
reg("AVERAGE", _agg(lambda xs: math.fsum(xs) / len(xs) if xs else DIV0), "The average of the numbers", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
reg("MIN", _agg(lambda xs: min(xs) if xs else 0.0), "The smallest number", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
reg("MAX", _agg(lambda xs: max(xs) if xs else 0.0), "The largest number", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")


def _median(xs):
    if not xs:
        return NUM
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _var(sample):
    def f(xs):
        n = len(xs)
        if n < (2 if sample else 1):
            return DIV0
        m = math.fsum(xs) / n
        return math.fsum((x - m) ** 2 for x in xs) / (n - 1 if sample else n)
    return f


reg("MEDIAN", _agg(_median), "The middle number", [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
for _n, _s in (("VAR", True), ("VAR.S", True), ("VAR.P", False)):
    reg(_n, _agg(_var(_s)), "Variance of " + ("a sample" if _s else "a whole population"), [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")
for _n, _s in (("STDEV", True), ("STDEV.S", True), ("STDEV.P", False)):
    reg(_n, _agg(lambda xs, f=_var(_s): (lambda v: v if isinstance(v, Err) else math.sqrt(v))(f(xs))),
        "Standard deviation of " + ("a sample" if _s else "a whole population"), [("number1", "A number or a range"), ("number2", "More", "rep")], kind="agg")


def _count(*args):
    n = 0
    for a in args:
        if isinstance(a, Arr):
            n += sum(1 for v in a.flat() if _is_num(v))
        elif _is_num(a) or isinstance(a, bool) or (isinstance(a, str) and str_to_num(a) is not None):
            n += 1
    return float(n)


reg("COUNT", _count, "How many cells hold a number", [("value1", "A value or a range"), ("value2", "More", "rep")], kind="agg")
reg("COUNTA", lambda *a: float(sum(1 for x in a for v in _flat(x) if v is not None)), "How many cells are not empty", [("value1", "A value or a range"), ("value2", "More", "rep")], kind="agg")
reg("COUNTBLANK", lambda a: float(sum(1 for v in _flat(a) if v is None or v == "")), "How many cells are empty", [("range", "The range")], kind="agg")


def _kth(big):
    def f(a, k):
        xs, err = _collect([a])
        if err is not None:
            return err
        kk = to_num(k)
        if isinstance(kk, Err):
            return kk
        kk = int(math.ceil(kk))
        if not 1 <= kk <= len(xs):
            return NUM
        return sorted(xs, reverse=big)[kk - 1]
    return f


reg("LARGE", _kth(True), "The k-th largest number", [("array", "The numbers"), ("k", "Which one (1 = largest)")], kind="agg")
reg("SMALL", _kth(False), "The k-th smallest number", [("array", "The numbers"), ("k", "Which one (1 = smallest)")], kind="agg")


def _crit(c):
    """A test for COUNTIF / SUMIF: a number, or text such as ">5", "<=3", "<>x", "abc*"."""
    if isinstance(c, Err):
        return None
    if isinstance(c, bool):
        return lambda v: isinstance(v, bool) and v == c
    if _is_num(c):
        return lambda v: _is_num(v) and float(v) == float(c)
    if c is None:
        return lambda v: _is_num(v) and v == 0
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", str(c), re.S)
    op, rhs = m.group(1) or "=", m.group(2)
    n = str_to_num(rhs) if rhs.strip() else None
    if n is not None:
        def num_test(v):
            x = float(v) if _is_num(v) else (str_to_num(v) if isinstance(v, str) else None)
            if x is None:
                return op == "<>"
            return {"=": x == n, "<>": x != n, "<": x < n, ">": x > n, "<=": x <= n, ">=": x >= n}[op]
        return num_test
    pat = rhs.casefold()
    wild = any(ch in pat for ch in "*?")

    def text_test(v):
        if isinstance(v, Err):
            return False
        s = "" if v is None else (to_text(v))
        s = s.casefold()
        if op in ("=", "<>"):
            same = fnmatch.fnmatchcase(s, pat) if wild else s == pat
            return same if op == "=" else not same
        return {"<": s < pat, ">": s > pat, "<=": s <= pat, ">=": s >= pat}[op]
    return text_test


def _pairs(*specs):
    """specs: [(range, criterion)...] -> indexes of the cells where every criterion holds, or an Err."""
    tests, flats = [], []
    for rng, cr in specs:
        t = _crit(cr)
        if t is None:
            return cr
        tests.append(t)
        flats.append(_flat(rng))
    n = len(flats[0])
    if any(len(f) != n for f in flats):
        return VALUE
    return [i for i in range(n) if all(t(f[i]) for t, f in zip(tests, flats))]


def _sumif(rng, cr, sr=None):
    idx = _pairs((rng, cr))
    if isinstance(idx, Err):
        return idx
    src = _flat(sr if sr is not None else rng)
    return math.fsum(float(src[i]) for i in idx if i < len(src) and _is_num(src[i]))


def _ifs(kind):
    def f(first, *rest):
        if kind in ("SUMIFS", "AVERAGEIFS", "MAXIFS", "MINIFS"):
            target, pairs = first, rest
        else:
            target, pairs = None, (first,) + rest
        if len(pairs) % 2:
            return VALUE
        idx = _pairs(*[(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)])
        if isinstance(idx, Err):
            return idx
        if kind == "COUNTIFS":
            return float(len(idx))
        src = _flat(target)
        xs = [float(src[i]) for i in idx if i < len(src) and _is_num(src[i])]
        if kind == "SUMIFS":
            return math.fsum(xs)
        if kind == "AVERAGEIFS":
            return math.fsum(xs) / len(xs) if xs else DIV0
        if kind == "MAXIFS":
            return max(xs) if xs else 0.0
        return min(xs) if xs else 0.0
    return f


reg("SUMIF", _sumif, "Adds the cells that meet a condition", [("range", "The cells to test"), ("criteria", 'The condition, such as ">5"'), ("sum_range", "The cells to add", "opt")], kind="agg")
reg("COUNTIF", lambda rng, cr: (lambda idx: idx if isinstance(idx, Err) else float(len(idx)))(_pairs((rng, cr))), "Counts the cells that meet a condition",
    [("range", "The cells to test"), ("criteria", 'The condition, such as ">5"')], kind="agg")
reg("AVERAGEIF", lambda rng, cr, sr=None: (lambda idx: idx if isinstance(idx, Err) else (lambda xs: math.fsum(xs) / len(xs) if xs else DIV0)(
    [float(_flat(sr if sr is not None else rng)[i]) for i in idx if _is_num(_flat(sr if sr is not None else rng)[i])]))(_pairs((rng, cr))),
    "Averages the cells that meet a condition", [("range", "The cells to test"), ("criteria", "The condition"), ("average_range", "The cells to average", "opt")], kind="agg")
for _n, _s in (("SUMIFS", "Adds the cells that meet all the conditions"), ("MAXIFS", "The largest number among the cells that meet all the conditions"),
               ("MINIFS", "The smallest number among the cells that meet all the conditions"), ("AVERAGEIFS", "Averages the cells that meet all the conditions")):
    reg(_n, _ifs(_n), _s, [("target_range", "The cells to use"), ("criteria_range1", "The cells to test"), ("criteria1", "The condition"),
                           ("criteria_range2", "More cells to test", "rep"), ("criteria2", "Its condition", "rep")], kind="agg")
register("COUNTIFS", _ifs("COUNTIFS"), kind="agg", lo=2, hi=None, summary="Counts the cells that meet all the conditions",
         args=(("criteria_range1", "The cells to test", ""), ("criteria1", "The condition", ""), ("criteria_range2", "More cells to test", "rep"), ("criteria2", "Its condition", "rep")))


def _sumproduct(*arrs):
    shapes = {(a.shape if isinstance(a, Arr) else (1, 1)) for a in arrs}
    if len(shapes) != 1:
        return VALUE
    lists = [_flat(a) for a in arrs]
    tot = 0.0
    for vals in zip(*lists):
        p = 1.0
        for v in vals:
            if isinstance(v, Err):
                return v
            p *= float(v) if _is_num(v) else 0.0
        tot += p
    return tot


reg("SUMPRODUCT", _sumproduct, "Multiplies ranges element by element and adds", [("array1", "A range"), ("array2", "More ranges", "rep")], kind="agg")


def _xy(ys, xs):
    a, b = _flat(ys), _flat(xs)
    if len(a) != len(b):
        return None, NA
    pts = []
    for y, x in zip(a, b):
        if isinstance(y, Err):
            return None, y
        if isinstance(x, Err):
            return None, x
        if _is_num(x) and _is_num(y):
            pts.append((float(x), float(y)))
    return pts, None


def _fit(ys, xs):
    pts, err = _xy(ys, xs)
    if err is not None:
        return err
    n = len(pts)
    if n < 2:
        return DIV0
    mx = math.fsum(p[0] for p in pts) / n
    my = math.fsum(p[1] for p in pts) / n
    sxx = math.fsum((p[0] - mx) ** 2 for p in pts)
    syy = math.fsum((p[1] - my) ** 2 for p in pts)
    sxy = math.fsum((p[0] - mx) * (p[1] - my) for p in pts)
    return mx, my, sxx, syy, sxy


def _slope(ys, xs):
    f = _fit(ys, xs)
    return f if isinstance(f, Err) else (DIV0 if f[2] == 0 else f[4] / f[2])


def _intercept(ys, xs):
    f = _fit(ys, xs)
    return f if isinstance(f, Err) else (DIV0 if f[2] == 0 else f[1] - f[4] / f[2] * f[0])


def _correl(a, b):
    f = _fit(a, b)
    return f if isinstance(f, Err) else (DIV0 if f[2] == 0 or f[3] == 0 else f[4] / math.sqrt(f[2] * f[3]))


reg("SLOPE", _slope, "Slope of the best straight line", [("known_y's", "The y values"), ("known_x's", "The x values")], kind="agg")
reg("INTERCEPT", _intercept, "Where the best straight line crosses y = 0", [("known_y's", "The y values"), ("known_x's", "The x values")], kind="agg")
reg("CORREL", _correl, "Correlation of two sets of numbers", [("array1", "The first set"), ("array2", "The second set")], kind="agg")
reg("RSQ", lambda a, b: (lambda r: r if isinstance(r, Err) else r * r)(_correl(a, b)), "R squared of the best straight line", [("known_y's", "The y values"), ("known_x's", "The x values")], kind="agg")
reg("FORECAST", lambda x, ys, xs: (lambda s, i, xx: s if isinstance(s, Err) else i if isinstance(i, Err) else xx if isinstance(xx, Err) else i + s * xx)(_slope(ys, xs), _intercept(ys, xs), to_num(x)),
    "Predicts a y value on the best straight line", [("x", "The x to predict at"), ("known_y's", "The y values"), ("known_x's", "The x values")], kind="agg")


# ------------------------------------------------------------------------------------------------------------------ logic
def _if(ev, ctx, nodes):
    c = ev(nodes[0])
    a = nodes[1] if len(nodes) > 1 else None
    b = nodes[2] if len(nodes) > 2 else None

    def pick(node, default):
        if node is None:
            return default
        if node[0] == "empty":
            return 0.0
        return ev(node)
    if isinstance(c, Arr):
        t, f = pick(a, True), pick(b, False)
        return map_n(lambda cc, x, y: cc if isinstance(cc, Err) else (lambda t_: t_ if isinstance(t_, Err) else (x if t_ else y))(to_bool(cc)), c, t, f)
    t_ = to_bool(c)
    if isinstance(t_, Err):
        return t_
    return pick(a, True) if t_ else pick(b, False)


def _iferror(only_na):
    def f(ev, ctx, nodes):
        v = ev(nodes[0])

        def bad(x):
            return x is NA if only_na else isinstance(x, Err)
        if isinstance(v, Arr):
            alt = ev(nodes[1])
            return map_n(lambda x, a: a if bad(x) else x, v, alt)
        return ev(nodes[1]) if bad(v) else v
    return f


def _ifs_fn(ev, ctx, nodes):
    if len(nodes) % 2:
        return VALUE
    for i in range(0, len(nodes), 2):
        t = to_bool(ev(nodes[i]))
        if isinstance(t, Err):
            return t
        if t:
            return ev(nodes[i + 1])
    return NA


def _choose(ev, ctx, nodes):
    i = to_num(ev(nodes[0]))
    if isinstance(i, Err):
        return i
    i = int(i)
    if not 1 <= i < len(nodes):
        return VALUE
    return ev(nodes[i])


reg("IF", _if, "Gives one value when a condition is true and another when it is false",
    [("logical_test", "The condition to test"), ("value_if_true", "Result when true"), ("value_if_false", "Result when false", "opt")], kind="lazy")
reg("IFERROR", _iferror(False), "Gives a different value when a formula is an error", [("value", "The formula to try"), ("value_if_error", "Result when it is an error")], kind="lazy")
reg("IFNA", _iferror(True), "Gives a different value when a formula is #N/A", [("value", "The formula to try"), ("value_if_na", "Result when it is #N/A")], kind="lazy")
register("IFS", _ifs_fn, kind="lazy", lo=2, hi=None, summary="Gives the result of the first condition that is true",
         args=(("logical_test1", "First condition", ""), ("value_if_true1", "Its result", ""), ("logical_test2", "Next condition", "rep"), ("value_if_true2", "Its result", "rep")))
register("CHOOSE", _choose, kind="lazy", lo=2, hi=None, summary="Picks the n-th of the values",
         args=(("index_num", "Which value (1, 2, ...)", ""), ("value1", "First value", ""), ("value2", "More values", "rep")))


def _bools(args):
    out = []
    for a in args:
        if isinstance(a, Arr):
            for v in a.flat():
                if isinstance(v, Err):
                    return None, v
                if isinstance(v, bool):
                    out.append(v)
                elif _is_num(v):
                    out.append(v != 0)
        else:
            b = to_bool(a) if a is not None else None
            if isinstance(b, Err):
                return None, b
            if b is not None:
                out.append(b)
    return out, None


def _logic(f):
    def g(*args):
        xs, err = _bools(args)
        return err if err is not None else (VALUE if not xs else f(xs))
    return g


reg("AND", _logic(all), "True when every condition is true", [("logical1", "A condition or range"), ("logical2", "More", "rep")], kind="agg")
reg("OR", _logic(any), "True when at least one condition is true", [("logical1", "A condition or range"), ("logical2", "More", "rep")], kind="agg")
reg("XOR", _logic(lambda xs: sum(xs) % 2 == 1), "True when an odd number of conditions are true", [("logical1", "A condition or range"), ("logical2", "More", "rep")], kind="agg")
reg("NOT", lambda v: (lambda b: b if isinstance(b, Err) else not b)(to_bool(v)), "Swaps true and false", [("logical", "The condition")])
reg("TRUE", lambda: True, "The value TRUE", [])
reg("FALSE", lambda: False, "The value FALSE", [])
reg("NA", lambda: NA, "The error #N/A, 'not available' (a chart leaves a gap there)", [])

reg("ISNUMBER", lambda v: _is_num(v), "True when the value is a number", [("value", "The value")])
reg("ISTEXT", lambda v: isinstance(v, str), "True when the value is text", [("value", "The value")])
reg("ISNONTEXT", lambda v: not isinstance(v, str), "True when the value is not text", [("value", "The value")])
reg("ISBLANK", lambda v: v is None, "True when the cell is empty", [("value", "The cell")])
reg("ISLOGICAL", lambda v: isinstance(v, bool), "True when the value is TRUE or FALSE", [("value", "The value")])
reg("ISERROR", lambda v: isinstance(v, Err), "True when the value is any error", [("value", "The value")])
reg("ISERR", lambda v: isinstance(v, Err) and v is not NA, "True when the value is an error other than #N/A", [("value", "The value")])
reg("ISNA", lambda v: v is NA, "True when the value is #N/A", [("value", "The value")])
reg("N", lambda v: v if isinstance(v, Err) else (float(v) if _is_num(v) else (1.0 if v is True else 0.0)), "The value as a number (text is 0)", [("value", "The value")])


# ------------------------------------------------------------------------------------------------------------------ lookup
def _cmp_key(v):
    return v.casefold() if isinstance(v, str) else v


def _same_kind(a, b):
    return (_is_num(a) and _is_num(b)) or (isinstance(a, str) and isinstance(b, str)) or (isinstance(a, bool) and isinstance(b, bool))


def _approx(v, vec):
    """Index of the largest entry that is <= v (the last of equal ones), like the binary search of LOOKUP on sorted data; None when there is none."""
    best = None
    for i, x in enumerate(vec):
        if isinstance(x, Err) or not _same_kind(v, x):
            continue
        if _cmp_key(x) <= _cmp_key(v) and (best is None or _cmp_key(x) >= _cmp_key(vec[best])):
            best = i
    return best


def _exact(v, vec):
    for i, x in enumerate(vec):
        if isinstance(x, Err):
            continue
        if isinstance(v, str) and isinstance(x, str):
            if (fnmatch.fnmatchcase(x.casefold(), v.casefold()) if any(c in v for c in "*?") else x.casefold() == v.casefold()):
                return i
        elif _same_kind(v, x) and x == v:
            return i
    return None


def _lookup(v, vec, res=None):
    if isinstance(v, Err):
        return v
    if isinstance(v, Arr):
        return VALUE
    if not isinstance(vec, Arr):
        vec = Arr([[vec]])
    r, c = vec.shape
    if res is None:
        if c >= r:                                         # the array form: search the first row, answer from the last row
            seq, out = vec.rows[0], vec.rows[-1]
        else:
            seq, out = [row[0] for row in vec.rows], [row[-1] for row in vec.rows]
    else:
        seq, out = _flat(vec), _flat(res)
    i = _approx(v, list(seq))
    if i is None or i >= len(out):
        return NA
    return out[i]


def _vlookup(v, table, col, approx=True):
    if isinstance(v, Err):
        return v
    if not isinstance(table, Arr):
        return REF
    ci = to_num(col)
    if isinstance(ci, Err):
        return ci
    ci = int(ci)
    if ci < 1:
        return VALUE
    if ci > table.shape[1]:
        return REF
    first = [row[0] for row in table.rows]
    ap = to_bool(approx) if approx is not None else True
    if isinstance(ap, Err):
        return ap
    i = _approx(v, first) if ap else _exact(v, first)
    return NA if i is None else table.rows[i][ci - 1]


def _hlookup(v, table, row, approx=True):
    if isinstance(v, Err):
        return v
    if not isinstance(table, Arr):
        return REF
    ri = to_num(row)
    if isinstance(ri, Err):
        return ri
    ri = int(ri)
    if ri < 1:
        return VALUE
    if ri > table.shape[0]:
        return REF
    first = table.rows[0]
    ap = to_bool(approx) if approx is not None else True
    if isinstance(ap, Err):
        return ap
    i = _approx(v, first) if ap else _exact(v, first)
    return NA if i is None else table.rows[ri - 1][i]


def _match(v, vec, mtype=1.0):
    if isinstance(v, Err):
        return v
    seq = _flat(vec)
    t = to_num(mtype if mtype is not None else 1.0)
    if isinstance(t, Err):
        return t
    if t == 0:
        i = _exact(v, seq)
    elif t > 0:
        i = _approx(v, seq)
    else:
        best = None
        for k, x in enumerate(seq):
            if not isinstance(x, Err) and _same_kind(v, x) and _cmp_key(x) >= _cmp_key(v) and (best is None or _cmp_key(x) <= _cmp_key(seq[best])):
                best = k
        i = best
    return NA if i is None else float(i + 1)


def _index(arr, r=None, c=None):
    if not isinstance(arr, Arr):
        arr = Arr([[arr]])
    nr, nc = arr.shape
    ri = 0 if r is None else to_num(r)
    ci = None if c is None else to_num(c)
    if isinstance(ri, Err):
        return ri
    if isinstance(ci, Err):
        return ci
    ri = int(ri)
    if ci is None:
        if nr == 1:                                        # INDEX(a row, n)
            ci, ri = ri, 1
        else:
            ci = 0
    ci = int(ci)
    if ri < 0 or ci < 0 or ri > nr or ci > nc:
        return REF
    if ri == 0 and ci == 0:
        return arr
    if ri == 0:
        return Arr([[row[ci - 1]] for row in arr.rows])
    if ci == 0:
        return Arr([list(arr.rows[ri - 1])])
    return arr.rows[ri - 1][ci - 1]


def _rc(axis):
    def f(ev, ctx, nodes):
        if not nodes:
            return float(ctx.row if axis == 0 else ctx.col)
        n = nodes[0]
        if n[0] != "ref":
            return VALUE
        t = n[1]
        r1, c1, r2, c2 = t.rect()
        if t.kind in ("col", "row") or (r1, c1) == (r2, c2):
            return float((r1, c1)[axis])
        if axis == 0:
            return Arr([[float(r)] for r in range(r1, r2 + 1)])
        return Arr([[float(c) for c in range(c1, c2 + 1)]])
    return f


reg("LOOKUP", _lookup, "Looks a value up in a sorted row or column", [("lookup_value", "The value to find"), ("lookup_vector", "The row or column to search"),
                                                                       ("result_vector", "The row or column to answer from", "opt")], kind="agg")
reg("VLOOKUP", _vlookup, "Looks down the first column of a table and answers from another column",
    [("lookup_value", "The value to find"), ("table_array", "The table"), ("col_index_num", "Which column to answer from"), ("range_lookup", "FALSE for an exact match", "opt")], kind="agg")
reg("HLOOKUP", _hlookup, "Looks along the first row of a table and answers from another row",
    [("lookup_value", "The value to find"), ("table_array", "The table"), ("row_index_num", "Which row to answer from"), ("range_lookup", "FALSE for an exact match", "opt")], kind="agg")
reg("MATCH", _match, "The position of a value in a row or column", [("lookup_value", "The value to find"), ("lookup_array", "The row or column"),
                                                                    ("match_type", "0 exact, 1 largest below, -1 smallest above", "opt")], kind="agg")
reg("INDEX", _index, "The value at a row and column of a range", [("array", "The range"), ("row_num", "Which row"), ("column_num", "Which column", "opt")], kind="agg")
reg("ROWS", lambda a: float(a.shape[0]) if isinstance(a, Arr) else 1.0, "How many rows a range has", [("array", "The range")], kind="agg")
reg("COLUMNS", lambda a: float(a.shape[1]) if isinstance(a, Arr) else 1.0, "How many columns a range has", [("array", "The range")], kind="agg")
reg("TRANSPOSE", lambda a: Arr([list(r) for r in zip(*a.rows)]) if isinstance(a, Arr) and a.rows else a, "Swaps rows and columns", [("array", "The range")], kind="agg")
reg("ROW", _rc(0), "The row number of a cell", [("reference", "The cell", "opt")], kind="lazy")
reg("COLUMN", _rc(1), "The column number of a cell", [("reference", "The cell", "opt")], kind="lazy")


# ------------------------------------------------------------------------------------------------------------------ text
def _s(v):
    return v if isinstance(v, Err) else to_text(v)


def _n(v, default=None):
    if v is None and default is not None:
        return float(default)
    return to_num(v)


def _left(t, n=1.0):
    s, k = _s(t), _n(n)
    if isinstance(s, Err):
        return s
    if isinstance(k, Err):
        return k
    return VALUE if k < 0 else s[:int(k)]


def _right(t, n=1.0):
    s, k = _s(t), _n(n)
    if isinstance(s, Err):
        return s
    if isinstance(k, Err):
        return k
    return VALUE if k < 0 else (s[len(s) - int(k):] if int(k) < len(s) else s)


def _mid(t, start, n):
    s, a, b = _s(t), _n(start), _n(n)
    for x in (s, a, b):
        if isinstance(x, Err):
            return x
    return VALUE if a < 1 or b < 0 else s[int(a) - 1:int(a) - 1 + int(b)]


def _substitute(t, old, new, inst=None):
    s, o, nw = _s(t), _s(old), _s(new)
    for x in (s, o, nw):
        if isinstance(x, Err):
            return x
    if o == "":
        return s
    if inst is None:
        return s.replace(o, nw)
    k = to_num(inst)
    if isinstance(k, Err) or k < 1:
        return VALUE
    parts = s.split(o)
    k = int(k)
    if k >= len(parts):
        return s
    return o.join(parts[:k]) + nw + o.join(parts[k:])


def _find(case):
    def f(needle, hay, start=1.0):
        a, b, st = _s(needle), _s(hay), _n(start, 1)
        for x in (a, b, st):
            if isinstance(x, Err):
                return x
        st = int(st)
        if st < 1 or st > len(b) + 1:
            return VALUE
        i = (b.find(a, st - 1) if case else b.casefold().find(a.casefold(), st - 1))
        return VALUE if i < 0 else float(i + 1)
    return f


def _concat_all(*args):
    out = []
    for a in args:
        for v in _flat(a):
            if isinstance(v, Err):
                return v
            out.append(to_text(v))
    return "".join(out)


def _textjoin(delim, skip, *args):
    d, sk = _s(delim), to_bool(skip)
    if isinstance(d, Err):
        return d
    if isinstance(sk, Err):
        return sk
    out = []
    for a in args:
        for v in _flat(a):
            if isinstance(v, Err):
                return v
            t = to_text(v)
            if t == "" and sk:
                continue
            out.append(t)
    return d.join(out)


def _text(v, fmt):
    if isinstance(v, Err):
        return v
    f = _s(fmt)
    if isinstance(f, Err):
        return f
    n = to_num(v) if not isinstance(v, str) else v
    return sh_fmt.show(n, f) if not isinstance(n, (Err, str)) else (to_text(v) if isinstance(n, str) else n)


def _value(v):
    if isinstance(v, Err):
        return v
    if _is_num(v):
        return float(v)
    n = str_to_num(to_text(v))
    return VALUE if n is None else n


def _trim(t):
    s = _s(t)
    return s if isinstance(s, Err) else re.sub(r" +", " ", s).strip(" ")


reg("LEFT", _left, "The first characters of text", [("text", "The text"), ("num_chars", "How many (1 if left out)", "opt")])
reg("RIGHT", _right, "The last characters of text", [("text", "The text"), ("num_chars", "How many (1 if left out)", "opt")])
reg("MID", _mid, "Characters from the middle of text", [("text", "The text"), ("start_num", "Where to start (1 = first)"), ("num_chars", "How many")])
reg("LEN", lambda t: (lambda s: s if isinstance(s, Err) else float(len(s)))(_s(t)), "How many characters", [("text", "The text")])
reg("UPPER", lambda t: (lambda s: s if isinstance(s, Err) else s.upper())(_s(t)), "Text in capitals", [("text", "The text")])
reg("LOWER", lambda t: (lambda s: s if isinstance(s, Err) else s.lower())(_s(t)), "Text in small letters", [("text", "The text")])
reg("PROPER", lambda t: (lambda s: s if isinstance(s, Err) else s.title())(_s(t)), "Capital letter on every word", [("text", "The text")])
reg("TRIM", _trim, "Removes extra spaces", [("text", "The text")])
reg("SUBSTITUTE", _substitute, "Replaces text inside text", [("text", "The text"), ("old_text", "What to replace"), ("new_text", "The replacement"), ("instance_num", "Which one (all if left out)", "opt")])
reg("REPT", lambda t, n: (lambda s, k: s if isinstance(s, Err) else k if isinstance(k, Err) else (VALUE if k < 0 else s * int(k)))(_s(t), to_num(n)), "Repeats text", [("text", "The text"), ("number_times", "How many times")])
reg("EXACT", lambda a, b: (lambda x, y: x if isinstance(x, Err) else y if isinstance(y, Err) else x == y)(_s(a), _s(b)), "True when two texts are exactly the same", [("text1", "First text"), ("text2", "Second text")])
reg("FIND", _find(True), "Where text starts inside other text (capitals matter)", [("find_text", "What to find"), ("within_text", "The text to search"), ("start_num", "Where to start", "opt")])
reg("SEARCH", _find(False), "Where text starts inside other text (capitals do not matter)", [("find_text", "What to find"), ("within_text", "The text to search"), ("start_num", "Where to start", "opt")])
reg("CONCATENATE", _concat_all, "Joins texts", [("text1", "A text"), ("text2", "More", "rep")], kind="agg")
reg("CONCAT", _concat_all, "Joins texts and ranges", [("text1", "A text or range"), ("text2", "More", "rep")], kind="agg")
reg("TEXTJOIN", _textjoin, "Joins texts with a separator", [("delimiter", "The separator"), ("ignore_empty", "TRUE to skip empty cells"), ("text1", "A text or range"), ("text2", "More", "rep")], kind="agg")
reg("TEXT", _text, "A number written with a number format", [("value", "The number"), ("format_text", 'The format, such as "0.00"')])
reg("VALUE", _value, "Text that looks like a number, as a number", [("text", "The text")])
reg("T", lambda v: v if isinstance(v, (str, Err)) else "", "The value if it is text, else nothing", [("value", "The value")])
reg("TODAY", lambda: float((datetime.date.today() - datetime.date(1899, 12, 30)).days), "Today's date as a number", [])
reg("NOW", lambda: (datetime.datetime.now() - datetime.datetime(1899, 12, 30)).total_seconds() / 86400.0, "The date and time now as a number", [])


# ------------------------------------------------------------------------------------------------------------------ CONVERT
_PREFIX = {"Y": 1e24, "Z": 1e21, "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "h": 1e2, "da": 1e1, "e": 1e1, "d": 1e-1, "c": 1e-2, "m": 1e-3,
           "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18, "z": 1e-21, "y": 1e-24}
# unit -> (dimension, size in the base unit, takes a metric prefix)
_UNITS = {
    "m": ("L", 1.0, 1), "in": ("L", 0.0254, 0), "ft": ("L", 0.3048, 0), "yd": ("L", 0.9144, 0), "mi": ("L", 1609.344, 0), "ang": ("L", 1e-10, 1), "nmi": ("L", 1852.0, 0),
    "g": ("M", 1.0, 1), "lbm": ("M", 453.59237, 0), "ozm": ("M", 28.349523125, 0), "stone": ("M", 6350.29318, 0), "ton": ("M", 907184.74, 0), "sg": ("M", 14593.9029, 0),
    "s": ("T", 1.0, 1), "sec": ("T", 1.0, 1), "min": ("T", 60.0, 0), "mn": ("T", 60.0, 0), "hr": ("T", 3600.0, 0), "day": ("T", 86400.0, 0), "d": ("T", 86400.0, 0), "yr": ("T", 31557600.0, 0),
    "Pa": ("P", 1.0, 1), "atm": ("P", 101325.0, 1), "mmHg": ("P", 133.322, 1), "psi": ("P", 6894.757293168, 1), "ksi": ("P", 6894757.293168, 0), "Torr": ("P", 133.3223684, 1), "bar": ("P", 1e5, 1),
    "N": ("F", 1.0, 1), "dyn": ("F", 1e-5, 1), "lbf": ("F", 4.4482216152605, 0), "kip": ("F", 4448.2216152605, 0), "pond": ("F", 0.00980665, 1), "kgf": ("F", 9.80665, 0),
    "J": ("E", 1.0, 1), "erg": ("E", 1e-7, 1), "cal": ("E", 4.1868, 1), "eV": ("E", 1.602176487e-19, 1), "Wh": ("E", 3600.0, 1), "BTU": ("E", 1055.05585262, 0), "flb": ("E", 1.3558179483314, 0),
    "W": ("W", 1.0, 1), "HP": ("W", 745.6998715823, 0), "PS": ("W", 735.49875, 0),
    "l": ("V", 0.001, 1), "L": ("V", 0.001, 1), "gal": ("V", 0.003785411784, 0), "qt": ("V", 0.000946352946, 0), "pt": ("V", 0.000473176473, 0), "cup": ("V", 0.0002365882365, 0),
    "oz": ("V", 2.95735295625e-5, 0), "tsp": ("V", 4.92892159375e-6, 0), "tbsp": ("V", 1.478676478125e-5, 0),
    "ha": ("A", 1e4, 0), "ac": ("A", 4046.8564224, 0), "us_acre": ("A", 4046.8564224, 0),
}
_DIMS = {"V": ("L", 3), "A": ("L", 2)}
_TEMP = {"C": (1.0, 273.15), "cel": (1.0, 273.15), "F": (5.0 / 9.0, 255.3722222222222), "fah": (5.0 / 9.0, 255.3722222222222), "K": (1.0, 0.0), "kel": (1.0, 0.0)}


def _unit(u):
    """(dimension, size in base units) as (symbol, power, factor), or None.  'ft^2', 'ft2' and 'cm^3' work; so do 'km', 'mm', 'kPa' ..."""
    m = re.match(r"^(.*?)(?:\^|)([23])$", u)
    power = 1
    base = u
    if m and m.group(1) and m.group(1) not in ("Pa",):
        cand = m.group(1)
        if _lookup_unit(cand) and _lookup_unit(cand)[0] == "L":
            base, power = cand, int(m.group(2))
    r = _lookup_unit(base)
    if r is None:
        return None
    dim, size = r
    if power > 1:
        return ("L", power, size ** power)
    if dim in _DIMS:
        d, p = _DIMS[dim]
        return (d, p, size)
    return (dim, 1, size)


def _lookup_unit(u):
    if u in _UNITS:
        d, f, _p = _UNITS[u]
        return d, f
    for k in (2, 1):
        if len(u) > k and u[:k] in _PREFIX and u[k:] in _UNITS and _UNITS[u[k:]][2]:
            d, f, _p = _UNITS[u[k:]]
            return d, f * _PREFIX[u[:k]]
    return None


def _convert(v, a, b):
    x, fa, fb = to_num(v), to_text(a), to_text(b)
    if isinstance(x, Err):
        return x
    if fa in _TEMP and fb in _TEMP:
        sa, oa = _TEMP[fa]
        sb, ob = _TEMP[fb]
        if fa in ("F", "fah"):
            kelvin = (x - 32.0) * 5.0 / 9.0 + 273.15
        elif fa in ("C", "cel"):
            kelvin = x + 273.15
        else:
            kelvin = x
        if fb in ("F", "fah"):
            return (kelvin - 273.15) * 9.0 / 5.0 + 32.0
        return kelvin - 273.15 if fb in ("C", "cel") else kelvin
    ua, ub = _unit(fa), _unit(fb)
    if ua is None or ub is None or ua[:2] != ub[:2]:
        return NA
    return x * ua[2] / ub[2]


reg("CONVERT", _convert, 'Converts a number between units, such as "in^2" to "ft^2" or "lbf" to "N"', [("number", "The value"), ("from_unit", 'Its unit, in quotes, such as "in"'), ("to_unit", 'The unit to convert to, such as "mm"')])
