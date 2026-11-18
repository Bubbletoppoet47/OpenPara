"""sh_fmt.py - how a value is written in a cell (number formats), with no window in it.

    show(value, fmt)  -> the text a cell displays.   fmt is an Excel number format: General, 0, 0.00, #,##0.00, 0.00E+00, 0%, 0.0%, @, 0.00 "psi" ...
    FORMATS           the formats the ribbon offers: [(label, fmt)]
"""
import math
import re

from sh_engine import Err

FORMATS = [("General", "General"), ("Number 0", "0"), ("Number 0.0", "0.0"), ("Number 0.00", "0.00"), ("Number 0.000", "0.000"), ("Number 0.0000", "0.0000"),
           ("Thousands 1,234", "#,##0"), ("Thousands 1,234.00", "#,##0.00"), ("Scientific 0.00E+00", "0.00E+00"), ("Percent 0%", "0%"),
           ("Percent 0.0%", "0.0%"), ("Text", "@")]

_QUOTED = re.compile(r'"([^"]*)"')


def general(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if v != v:
        return "#NUM!"
    if v in (math.inf, -math.inf):
        return "#NUM!"
    if v == int(v) and abs(v) < 1e11:
        return str(int(v))
    s = f"{v:.10g}"
    if "e" in s:
        m, e = s.split("e")
        s = m + "E" + e[0] + e[1:].lstrip("0").rjust(2, "0")
    return s


def _round_half_up(x, nd):
    q = 10 ** nd
    y = abs(x) * q
    f = math.floor(y + 0.5 + 1e-9 * max(1.0, y) * 1e-3)
    return math.copysign(f / q, x)


def _group(s):
    head, _, tail = s.partition(".")
    neg = head.startswith("-")
    head = head.lstrip("-")
    parts = []
    while len(head) > 3:
        parts.insert(0, head[-3:])
        head = head[:-3]
    parts.insert(0, head)
    return ("-" if neg else "") + ",".join(parts) + ("." + tail if tail else "")


def number(v, fmt):
    """A number written with a number format (a format with no placeholder in it shows the number as General)."""
    sec = fmt.split(";")
    body = sec[0]
    if v < 0 and len(sec) > 1:
        body, v = sec[1], -v
    elif v == 0 and len(sec) > 2:
        body = sec[2]
    lits = []

    def keep(m):
        lits.append(m.group(1))
        return "\x00"
    pat = _QUOTED.sub(keep, body).replace("\\", "")
    pct = "%" in pat
    pat = re.sub(r"_.|\*.", "", pat)
    m = re.search(r"[#0?][#0?,]*(?:\.[0#?]*)?(?:[Ee][+-][0#]+)?", pat)
    if not m:
        return general(v)
    core = m.group(0)
    pre, post = pat[:m.start()], pat[m.end():]
    exp = re.search(r"[Ee]([+-])([0#]+)$", core)
    if exp:
        core = core[:exp.start()]
    ip, _, dp = core.partition(".")
    thousands = "," in ip
    nd = len(dp)
    val = v * 100.0 if pct else v
    if exp:
        if val == 0:
            e10 = 0
        else:
            e10 = int(math.floor(math.log10(abs(val))))
        mant = val / (10 ** e10)
        if round(abs(mant), nd) >= 10:
            mant, e10 = mant / 10, e10 + 1
        txt = f"{mant:.{nd}f}" + exp.group(0)[0] + ("-" if e10 < 0 else ("+" if exp.group(1) == "+" else "")) + str(abs(e10)).rjust(len(exp.group(2)), "0")
    else:
        r = _round_half_up(val, nd)
        txt = f"{r:.{nd}f}"
        minint = ip.replace(",", "").count("0")
        head, _, tail = txt.partition(".")
        neg = head.startswith("-")
        head = head.lstrip("-")
        if minint == 0 and head == "0" and nd > 0:
            head = ""
        elif len(head) < minint:
            head = head.rjust(minint, "0")
        txt = ("-" if neg and (r != 0) else "") + head + ("." + tail if tail else "")
        if thousands:
            txt = _group(txt)
    out = pre + txt + post
    for s in lits:
        out = out.replace("\x00", s, 1)
    return out


def show(v, fmt="General"):
    """The text of a cell value."""
    if v is None:
        return ""
    if isinstance(v, Err):
        return v.code
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if fmt in (None, "", "General", "@"):
        return general(float(v))
    try:
        return number(float(v), fmt)
    except (ValueError, OverflowError):
        return general(float(v))


def decimals_of(fmt):
    """How many decimals a number format shows (None for General / not a number format)."""
    m = re.search(r"\.([0#]+)", fmt or "")
    if fmt in (None, "", "General", "@"):
        return None
    return len(m.group(1)) if m else 0


def with_decimals(fmt, nd):
    """The number format `fmt` written with `nd` decimals (the 'increase / decrease decimals' buttons)."""
    nd = max(0, min(15, nd))
    f = fmt if fmt not in (None, "", "General", "@") else "0"
    dec = "." + "0" * nd if nd else ""
    if re.search(r"\.[0#]+", f):
        return re.sub(r"\.[0#]+", dec, f, count=1)
    return re.sub(r"([#0][#0,]*)", lambda m: m.group(1) + dec, f, count=1)
