"""
sh_std.py - engineering standards as cell formulas: the registry that the Standards window, the Function Arguments window and the formula engine share.

A standard is a Pack: its short code ("AISI S100-16"), full title, edition, publisher and its functions.  A function (StdFunc) is one check or equation of the
standard, written as an Excel-style formula such as  =AISI16.J4_4_1(tc, d, Fu2) .  It knows its section and equation number, the formula in readable form, its
arguments (symbol, meaning, units, limits), a few notes, and a worked example that is computed when it is shown.

Adding a standard = a module that builds a Pack and calls register_pack(pack).  Another add-on can offer one through the hook "sheets_standard"
(ext.add_hook("sheets_standard", fn) where fn() returns a Pack or a list of them).

Rules the functions follow (each one's notes say more):
* Units are inches, psi and lbf (stresses in psi, forces in lbf, lengths in inches).
* The last argument of a strength function is the method: "nominal" (the default), "ASD" (nominal / omega), "LRFD" or "LSD" (phi x nominal).
* An input outside the limits the standard states does not stop the calculation: the cell gets a small orange marker and the message says what was out of range.
"""
import math
import types

import sh_engine as E

PACKS = {}              # id -> Pack
_BY_NAME = {}           # function name (upper case) -> StdFunc
METHODS = ("nominal", "ASD", "LRFD", "LSD")


class Arg:
    """One argument.  kind: num | text.  min / max / limit_ref: the range the standard states (the cell is marked when the value is outside).
    positive: the value must be above zero (a thickness); choices: the words a text argument takes."""
    __slots__ = ("name", "symbol", "meaning", "units", "kind", "optional", "default", "choices", "min", "max", "limit_ref", "positive", "example")

    def __init__(self, name, meaning, units="", kind="num", optional=False, default=None, choices=None, min=None, max=None, limit_ref="", positive=True,
                 symbol=None, example=None):
        self.name, self.meaning, self.units, self.kind = name, meaning, units, kind
        self.symbol = symbol or name
        self.optional, self.default, self.choices = optional, default, tuple(choices) if choices else None
        self.min, self.max, self.limit_ref, self.positive, self.example = min, max, limit_ref, positive, example

    def limits_text(self):
        if self.kind == "text":
            return "one of: " + ", ".join(self.choices) if self.choices else ""
        if self.min is not None and self.max is not None:
            return f"{_g(self.min)} to {_g(self.max)} {self.units}".strip()
        if self.max is not None:
            return f"at most {_g(self.max)} {self.units}".strip()
        if self.min is not None:
            return f"at least {_g(self.min)} {self.units}".strip()
        return "above 0" if self.positive and self.kind == "num" and not self.optional else ""


def _g(x):
    return f"{x:g}"


class StdFunc:
    def __init__(self, name, section, title, brief, formula, args, impl, path, eq="", units="lbf", factors=None, notes=(), keywords="", check=False, default_method=None):
        self.name = name                       # "J4_4_1"; the cell formula says AISI16.J4_4_1
        self.section, self.eq, self.title, self.brief = section, eq, title, brief
        self.formula, self.units, self.notes, self.keywords = formula, units, tuple(notes), keywords
        self.args = list(args)
        self.impl, self.path = impl, tuple(path)
        self.factors = factors                 # (omega, phi LRFD, phi LSD) of the main case, shown in the window
        self.check = check
        self.default_method = default_method
        self.pack = None
        self.example = None                    # filled in by register_pack

    @property
    def full_name(self):
        return f"{self.pack.prefix}.{self.name}"

    @property
    def arg_names(self):
        return [a.name for a in self.args]

    def formula_text(self, values=None):
        """'=AISI16.J4_4_1(tc, d, Fu2)' with the argument names (or the given values) in place."""
        vals = values if values is not None else [a.name for a in self.args]
        keep = len(vals)
        while keep > 0 and values is None and self.args[keep - 1].optional:
            keep -= 1
        return f"={self.full_name}({', '.join(str(v) for v in vals[:keep])})"

    def factors_text(self):
        if not self.factors:
            return ""
        o, p, pl = self.factors
        return f"Ω = {o:.2f} (ASD),  φ = {p:.2f} (LRFD),  φ = {pl:.2f} (LSD)"


class Pack:
    def __init__(self, id, prefix, short, title, edition, publisher, funcs, root="", about=""):
        self.id, self.prefix, self.short, self.title = id, prefix, short, title
        self.edition, self.publisher, self.root, self.about = edition, publisher, root, about
        self.funcs = list(funcs)

    def tree(self):
        """{label: {label: [StdFunc]}} grouped by each function's path (the first levels of it)."""
        out = {}
        for f in self.funcs:
            node = out
            for p in f.path[:-1]:
                node = node.setdefault(p, {})
            node.setdefault(f.path[-1], []).append(f)
        return out


# ------------------------------------------------------------------------------------------------------------------ calling a function
def _method(m, default):
    if m is None or m == "":
        return default or "nominal"
    u = str(m).strip().upper()
    for k in METHODS:
        if u == k.upper() or (u in ("N", "PN") and k == "nominal"):
            return k
    return None


def _wrap(sf):
    """The engine function of a StdFunc: checks and converts the arguments, marks values outside the stated limits, and calls the equation."""
    all_args = list(sf.args)
    if sf.factors is not None or sf.check:
        all_args = all_args + [Arg("method", "nominal, ASD, LRFD or LSD", kind="text", optional=True, choices=METHODS, positive=False, symbol="method")]

    def fn(ctx, *vals):
        a = types.SimpleNamespace()
        for i, ar in enumerate(all_args):
            v = vals[i] if i < len(vals) else None
            if isinstance(v, E.Err):
                return v
            if ar.name == "method":
                m = _method(v, sf.default_method or ("ASD" if sf.check else None))
                if m is None:
                    ctx.warn('method must be "nominal", "ASD", "LRFD" or "LSD"')
                    return E.VALUE
                a.method = m
                continue
            if v is None or (isinstance(v, str) and v == ""):
                if not ar.optional:
                    ctx.warn(f"{ar.symbol} ({ar.meaning}) is empty")
                    return E.VALUE
                setattr(a, ar.name, ar.default)
                continue
            if ar.kind == "text":
                t = E.to_text(v).strip().upper()
                if ar.choices and t not in [c.upper() for c in ar.choices]:
                    ctx.warn(f'{ar.symbol} must be one of: {", ".join(ar.choices)}')
                    return E.VALUE
                setattr(a, ar.name, t)
                continue
            x = E.to_num(v)
            if isinstance(x, E.Err):
                ctx.warn(f"{ar.symbol} is not a number")
                return x
            if ar.positive and x <= 0:
                ctx.warn(f"{ar.symbol} ({ar.meaning}) must be above 0")
                return E.NUM
            if not ar.positive and x < 0 and ar.min is None:
                ctx.warn(f"{ar.symbol} ({ar.meaning}) must not be negative")
                return E.NUM
            lo, hi = ar.min, ar.max
            if (lo is not None and x < lo) or (hi is not None and x > hi):
                ref = f" ({ar.limit_ref})" if ar.limit_ref else ""
                ctx.warn(f"{ar.symbol} = {x:g} {ar.units} is outside the stated limits, {ar.limits_text()}{ref}")
            setattr(a, ar.name, x)
        m = getattr(a, "method", sf.default_method or "nominal")

        def fac(omega, phi, phil):
            return {"nominal": 1.0, "ASD": 1.0 / omega, "LRFD": phi, "LSD": phil}[m]

        def cap(c, omega, phi, phil):
            """What a combined-load sum may reach: c / omega for ASD, c x phi for LRFD / LSD (nominal is read as ASD)."""
            return {"nominal": c / omega, "ASD": c / omega, "LRFD": c * phi, "LSD": c * phil}[m]
        a.fac, a.cap, a.warn = fac, cap, ctx.warn
        try:
            r = sf.impl(a)
        except ZeroDivisionError:
            return E.DIV0
        except (ValueError, OverflowError):
            return E.NUM
        if isinstance(r, E.Err):
            return r
        if isinstance(r, complex) or r != r or r in (math.inf, -math.inf):
            return E.NUM
        return float(r)
    return fn, all_args


def register_pack(pack):
    """Adds a standard: its functions become formulas (AISI16.J4_4_1 ...) and appear in the Standards window."""
    PACKS[pack.id] = pack
    for sf in pack.funcs:
        sf.pack = pack
        fn, all_args = _wrap(sf)
        sf.all_args = all_args
        lo = sum(1 for x in all_args if not x.optional)
        E.register(sf.full_name, fn, kind="scalar", lo=lo, hi=len(all_args), summary=sf.brief, ctx=True, pack=pack.id,
                   args=[(x.name, f"{x.meaning}" + (f" [{x.units}]" if x.units else ""), "opt" if x.optional else "") for x in all_args])
        _BY_NAME[sf.full_name.upper()] = sf
        sf.example = _example(sf)


def _example(sf):
    """The worked example: the argument values given by the arguments' `example`, and the result worked out now."""
    vals = [x.example for x in sf.args]
    if any(v is None for v, x in zip(vals, sf.args) if not x.optional):
        return None
    ctx = _Quiet()
    fn = E.FUNCS[sf.full_name.upper()].fn
    r = fn(ctx, *vals)
    return {"values": vals, "result": r, "warnings": ctx.msgs}


class _Quiet:
    def __init__(self):
        self.msgs = []

    def warn(self, t):
        self.msgs.append(t)


def packs():
    return list(PACKS.values())


def pack(pid):
    return PACKS.get(pid)


def func(name):
    """The StdFunc for a formula function name ('AISI16.J4_4_1'), or None."""
    return _BY_NAME.get(str(name).upper())


def all_funcs():
    return list(_BY_NAME.values())


def search(text, pack_id=None):
    """The functions whose title, section, equation, short description or keywords contain every word of `text`."""
    words = [w for w in text.casefold().split() if w]
    out = []
    for f in _BY_NAME.values():
        if pack_id and f.pack.id != pack_id:
            continue
        hay = " ".join([f.section, f.eq, f.title, f.brief, f.keywords, " ".join(f.path), f.name, " ".join(a.symbol for a in f.args)]).casefold()
        if all(w in hay for w in words):
            out.append(f)
    return out


def load_hooks():
    """Standards that other add-ons offer through the 'sheets_standard' hook."""
    try:
        import ext
        for fn in ext.hooks("sheets_standard"):
            try:
                r = fn()
            except Exception:                                  # noqa: BLE001 - one broken add-on must not break the window
                continue
            for p in (r if isinstance(r, (list, tuple)) else [r]):
                if isinstance(p, Pack) and p.id not in PACKS:
                    register_pack(p)
    except ImportError:
        pass
