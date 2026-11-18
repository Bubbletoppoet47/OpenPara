"""
sh_engine.py - the formula language of Sheets, with no window in it.  Excel-compatible: the same syntax, the same operator order, the same errors.

    parse(text)                      -> Parsed(ast, refs, names)      (cached; raises FormulaError for a formula that cannot be read)
    evaluate(ast, ctx)               -> value                         (a number, text, True/False, None for an empty cell, an Err, or an Arr)
    shift_formula(text, dr, dc)      the formula as it reads after being copied dr rows down and dc columns right ($ parts stay)
    adjust_formula(...)              the formula after rows / columns were inserted or deleted;  rename_sheet(text, old, new)

A cell value is a float, a str, a bool, None (empty) or an Err (#DIV/0!, #N/A, #VALUE!, #REF!, #NAME?, #NUM!).  A range is an Arr (rows of values).
The functions live in sh_funcs.py and add themselves to FUNCS; a standard (AISI S100-16 ...) adds its own the same way (sh_std.py).
The context `ctx` (the workbook) gives:  ctx.sheet, ctx.row, ctx.col (the cell being worked out), ctx.value(sheet, r, c), ctx.extent(sheet) -> (rows, cols
in use), ctx.name_target(name) -> ast or None, ctx.warn(text).
"""
import functools
import math
import re

MAXROW = 1048576
MAXCOL = 16384


# ------------------------------------------------------------------------------------------------------------------ errors and arrays
class Err:
    """An Excel error value.  One object per code, so `v is NA` works."""
    __slots__ = ("code",)
    _all = {}

    def __new__(cls, code):
        o = cls._all.get(code)
        if o is None:
            o = object.__new__(cls)
            o.code = code
            cls._all[code] = o
        return o

    def __repr__(self):
        return self.code

    __str__ = __repr__


DIV0, NA, VALUE, REF, NAME, NUM, NULL, CIRC = (Err(c) for c in ("#DIV/0!", "#N/A", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!", "#CIRC!"))
ERROR_CODES = {e.code: e for e in (DIV0, NA, VALUE, REF, NAME, NUM, NULL, CIRC)}


class FormulaError(Exception):
    """A formula that cannot be read (the text is not a formula Excel would accept)."""

    def __init__(self, msg, pos=0):
        super().__init__(msg)
        self.msg = msg
        self.pos = pos


class Arr:
    """A block of values (what a range or an array calculation gives): rows of values."""
    __slots__ = ("rows",)

    def __init__(self, rows):
        self.rows = rows

    @property
    def shape(self):
        return len(self.rows), (len(self.rows[0]) if self.rows else 0)

    def flat(self):
        for r in self.rows:
            yield from r

    def __repr__(self):
        return f"Arr({self.rows})"


# ------------------------------------------------------------------------------------------------------------------ addresses
def col_letter(c):
    s = ""
    while c > 0:
        c, m = divmod(c - 1, 26)
        s = chr(65 + m) + s
    return s


def col_index(s):
    n = 0
    for ch in s.upper():
        n = n * 26 + ord(ch) - 64
    return n


_ADDR = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def parse_addr(text):
    """'B12' (or '$B$12') -> (12, 2); None when it is not a cell address."""
    m = _ADDR.match(text.strip())
    if not m:
        return None
    r, c = int(m.group(2)), col_index(m.group(1))
    if not (1 <= r <= MAXROW and 1 <= c <= MAXCOL):
        return None
    return r, c


def addr(r, c, abs_r=False, abs_c=False):
    return ("$" if abs_c else "") + col_letter(c) + ("$" if abs_r else "") + str(r)


def quote_sheet(name):
    """The sheet name as it is written in front of a reference: quoted when it needs to be."""
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name) and not _ADDR.match(name) and name.upper() not in ("TRUE", "FALSE"):
        return name
    return "'" + name.replace("'", "''") + "'"


def unquote_sheet(text):
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    return text


# ------------------------------------------------------------------------------------------------------------------ the references in a formula
class RefTok:
    """A reference as written: [Sheet!]A1, [Sheet!]A1:B5, [Sheet!]A:A, [Sheet!]3:5.  r1..c2 are 1-based; ar1.. say 'written with a $'."""
    __slots__ = ("prefix", "kind", "r1", "c1", "r2", "c2", "ar1", "ac1", "ar2", "ac2")

    def __init__(self, prefix, kind, r1, c1, r2, c2, ar1, ac1, ar2, ac2):
        self.prefix, self.kind = prefix, kind
        self.r1, self.c1, self.r2, self.c2 = r1, c1, r2, c2
        self.ar1, self.ac1, self.ar2, self.ac2 = ar1, ac1, ar2, ac2

    @property
    def sheet(self):
        return unquote_sheet(self.prefix[:-1]) if self.prefix else None

    @property
    def is_range(self):
        return self.kind != "cell"

    def text(self):
        p = self.prefix
        if self.kind == "cell":
            return p + addr(self.r1, self.c1, self.ar1, self.ac1)
        if self.kind == "range":
            return p + addr(self.r1, self.c1, self.ar1, self.ac1) + ":" + addr(self.r2, self.c2, self.ar2, self.ac2)
        if self.kind == "col":
            return p + ("$" if self.ac1 else "") + col_letter(self.c1) + ":" + ("$" if self.ac2 else "") + col_letter(self.c2)
        return p + ("$" if self.ar1 else "") + str(self.r1) + ":" + ("$" if self.ar2 else "") + str(self.r2)

    def copy(self):
        return RefTok(self.prefix, self.kind, self.r1, self.c1, self.r2, self.c2, self.ar1, self.ac1, self.ar2, self.ac2)

    def rect(self):
        return min(self.r1, self.r2), min(self.c1, self.c2), max(self.r1, self.r2), max(self.c1, self.c2)


_SHEET = r"(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_\.]*)!"
_CELL = r"\$?[A-Za-z]{1,3}\$?\d+"
_COLR = r"\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}"
_ROWR = r"\$?\d+:\$?\d+"
_REF_RE = re.compile(rf"(?P<sheet>{_SHEET})?(?:(?P<range>{_CELL}:{_CELL})|(?P<cell>{_CELL})|(?P<col>{_COLR})|(?P<row>{_ROWR}))")
_NUM_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_ID_RE = re.compile(r"[A-Za-z_\\][A-Za-z0-9_\.]*")
_ERR_RE = re.compile(r"#(?:DIV/0!|N/A|VALUE!|REF!|NAME\?|NUM!|NULL!)")
_PART = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)$")


def _cell_parts(s):
    m = _PART.match(s)
    return int(m.group(4)), col_index(m.group(2)), bool(m.group(3)), bool(m.group(1))


def _make_ref(m):
    prefix = m.group("sheet") or ""
    if m.group("cell"):
        r, c, ar, ac = _cell_parts(m.group("cell"))
        t = RefTok(prefix, "cell", r, c, r, c, ar, ac, ar, ac)
    elif m.group("range"):
        a, b = m.group("range").split(":")
        r1, c1, ar1, ac1 = _cell_parts(a)
        r2, c2, ar2, ac2 = _cell_parts(b)
        t = RefTok(prefix, "range", r1, c1, r2, c2, ar1, ac1, ar2, ac2)
    elif m.group("col"):
        a, b = m.group("col").split(":")
        ac1, ac2 = a.startswith("$"), b.startswith("$")
        t = RefTok(prefix, "col", 1, col_index(a.lstrip("$")), MAXROW, col_index(b.lstrip("$")), True, ac1, True, ac2)
    else:
        a, b = m.group("row").split(":")
        ar1, ar2 = a.startswith("$"), b.startswith("$")
        t = RefTok(prefix, "row", int(a.lstrip("$")), 1, int(b.lstrip("$")), MAXCOL, ar1, True, ar2, True)
    if not (1 <= t.r1 <= MAXROW and 1 <= t.r2 <= MAXROW and 1 <= t.c1 <= MAXCOL and 1 <= t.c2 <= MAXCOL):
        return None
    return t


# a token: (kind, text, start, end, value)   kinds: num str bool err ref name func op lp rp comma semi lb rb
def tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j, buf = i + 1, []
            while True:
                if j >= n:
                    raise FormulaError("The text in quotes is not closed.", i)
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            toks.append(("str", text[i:j + 1], i, j + 1, "".join(buf)))
            i = j + 1
            continue
        if ch == "#":
            m = _ERR_RE.match(text, i)
            if not m:
                raise FormulaError("Unknown error value.", i)
            toks.append(("err", m.group(0), i, m.end(), ERROR_CODES[m.group(0)]))
            i = m.end()
            continue
        if ch.isalpha() or ch in "_$'\\" or ch.isdigit() or ch == ".":
            m = _REF_RE.match(text, i)
            if m and ch != ".":
                end = m.end()
                nxt = text[end] if end < n else ""
                if not (nxt != "" and (nxt.isalnum() or nxt in "_.(")):
                    t = _make_ref(m)
                    if t is not None:
                        toks.append(("ref", text[i:end], i, end, t))
                        i = end
                        continue
            if ch.isdigit() or ch == ".":
                m = _NUM_RE.match(text, i)
                if not m:
                    raise FormulaError("Unexpected '.'", i)
                toks.append(("num", m.group(0), i, m.end(), float(m.group(0))))
                i = m.end()
                continue
            m = _ID_RE.match(text, i)
            if not m:
                raise FormulaError(f"Unexpected '{ch}'", i)
            word, end = m.group(0), m.end()
            k = end
            while k < n and text[k].isspace():
                k += 1
            if k < n and text[k] == "(":
                toks.append(("func", word, i, end, word.upper()))
            elif word.upper() in ("TRUE", "FALSE"):
                toks.append(("bool", word, i, end, word.upper() == "TRUE"))
            else:
                toks.append(("name", word, i, end, word))
            i = end
            continue
        two = text[i:i + 2]
        if two in ("<=", ">=", "<>"):
            toks.append(("op", two, i, i + 2, two))
            i += 2
            continue
        if ch in "+-*/^&=<>%":
            toks.append(("op", ch, i, i + 1, ch))
        elif ch == "(":
            toks.append(("lp", ch, i, i + 1, ch))
        elif ch == ")":
            toks.append(("rp", ch, i, i + 1, ch))
        elif ch == ",":
            toks.append(("comma", ch, i, i + 1, ch))
        elif ch == ";":
            toks.append(("semi", ch, i, i + 1, ch))
        elif ch == "{":
            toks.append(("lb", ch, i, i + 1, ch))
        elif ch == "}":
            toks.append(("rb", ch, i, i + 1, ch))
        else:
            raise FormulaError(f"Unexpected '{ch}'", i)
        i += 1
    return toks


# ------------------------------------------------------------------------------------------------------------------ the parser
# nodes:  ("num", x) ("str", s) ("bool", b) ("err", e) ("ref", RefTok) ("name", ident) ("call", NAME, [nodes]) ("un", op, a) ("bin", op, a, b)
#         ("pct", a) ("arr", [[nodes]]) ("empty",)
class Parser:
    def __init__(self, toks, text):
        self.t, self.i, self.text = toks, 0, text

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def fail(self, msg):
        tok = self.peek()
        raise FormulaError(msg, tok[2] if tok else len(self.text))

    def parse(self):
        if not self.t:
            raise FormulaError("The formula is empty.", 0)
        node = self.cmp()
        if self.peek() is not None:
            self.fail("There is something extra after the end of the formula." if self.peek()[0] != "rp" else "A closing bracket has no opening bracket.")
        return node

    def cmp(self):
        a = self.concat()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[4]
            a = ("bin", op, a, self.concat())
        return a

    def concat(self):
        a = self.add()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] == "&":
            self.take()
            a = ("bin", "&", a, self.add())
        return a

    def add(self):
        a = self.mul()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] in ("+", "-"):
            op = self.take()[4]
            a = ("bin", op, a, self.mul())
        return a

    def mul(self):
        a = self.pow()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] in ("*", "/"):
            op = self.take()[4]
            a = ("bin", op, a, self.pow())
        return a

    def pow(self):
        a = self.unary()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] == "^":
            self.take()
            a = ("bin", "^", a, self.unary())
        return a

    def unary(self):
        tok = self.peek()
        if tok and tok[0] == "op" and tok[4] in ("+", "-"):
            self.take()
            a = self.unary()
            return ("un", tok[4], a) if tok[4] == "-" else a
        return self.postfix()

    def postfix(self):
        a = self.primary()
        while self.peek() and self.peek()[0] == "op" and self.peek()[4] == "%":
            self.take()
            a = ("pct", a)
        return a

    def primary(self):
        tok = self.peek()
        if tok is None:
            self.fail("The formula ends too early.")
        k = tok[0]
        if k == "num":
            self.take()
            return ("num", tok[4])
        if k == "str":
            self.take()
            return ("str", tok[4])
        if k == "bool":
            self.take()
            return ("bool", tok[4])
        if k == "err":
            self.take()
            return ("err", tok[4])
        if k == "ref":
            self.take()
            return ("ref", tok[4])
        if k == "name":
            self.take()
            return ("name", tok[4])
        if k == "lp":
            self.take()
            a = self.cmp()
            if not self.peek() or self.peek()[0] != "rp":
                self.fail("A bracket is not closed.")
            self.take()
            return a
        if k == "func":
            self.take()
            self.take()                                     # the "("
            args = []
            nx = self.peek()
            if nx and nx[0] == "rp":
                self.take()
                return ("call", tok[4], args)
            while True:
                nx = self.peek()
                if nx is None:
                    self.fail("A bracket is not closed.")
                if nx[0] in ("comma", "rp"):
                    args.append(("empty",))
                else:
                    args.append(self.cmp())
                nx = self.peek()
                if nx is None:
                    self.fail("A bracket is not closed.")
                if nx[0] == "comma":
                    self.take()
                    continue
                if nx[0] == "rp":
                    self.take()
                    break
                self.fail("Expected a comma or a closing bracket.")
            return ("call", tok[4], args)
        if k == "lb":
            self.take()
            rows, row = [], []
            while True:
                row.append(self.cmp())
                nx = self.peek()
                if nx is None:
                    self.fail("An array { } is not closed.")
                if nx[0] == "comma":
                    self.take()
                elif nx[0] == "semi":
                    self.take()
                    rows.append(row)
                    row = []
                elif nx[0] == "rb":
                    self.take()
                    rows.append(row)
                    break
                else:
                    self.fail("Expected a comma, a semicolon or } in the array.")
            return ("arr", rows)
        self.fail(f"Unexpected '{tok[1]}'.")


class Parsed:
    __slots__ = ("ast", "refs", "names", "calls")

    def __init__(self, ast, refs, names, calls):
        self.ast, self.refs, self.names, self.calls = ast, refs, names, calls


def _walk(node, refs, names, calls):
    k = node[0]
    if k == "ref":
        refs.append(node[1])
    elif k == "name":
        names.append(node[1])
    elif k == "call":
        calls.append(node[1])
        for a in node[2]:
            _walk(a, refs, names, calls)
    elif k == "un" or k == "pct":
        _walk(node[2] if k == "un" else node[1], refs, names, calls)
    elif k == "bin":
        _walk(node[2], refs, names, calls)
        _walk(node[3], refs, names, calls)
    elif k == "arr":
        for row in node[1]:
            for x in row:
                _walk(x, refs, names, calls)


@functools.lru_cache(maxsize=50000)
def parse(text):
    """Parsed formula; `text` is the formula with or without the leading '='."""
    body = text[1:] if text.startswith("=") else text
    ast = Parser(tokenize(body), body).parse()
    refs, names, calls = [], [], []
    _walk(ast, refs, names, calls)
    return Parsed(ast, tuple(refs), tuple(names), tuple(calls))


def check(text):
    """None when the formula can be read, else a short message."""
    try:
        parse(text)
        return None
    except FormulaError as e:
        return e.msg


# ------------------------------------------------------------------------------------------------------------------ values
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")


def str_to_num(s):
    t = s.strip()
    if not t:
        return None
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    low = t.lower()
    if low in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity") or "_" in t:
        return None
    try:
        v = float(t)
    except ValueError:
        if _THOUSANDS.match(t):
            v = float(t.replace(",", ""))
        else:
            return None
    return v / 100.0 if pct else v


def to_num(v):
    """A value as a number for arithmetic: a float, or an Err."""
    if isinstance(v, float):
        return v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, int):
        return float(v)
    if v is None:
        return 0.0
    if isinstance(v, str):
        n = str_to_num(v)
        return VALUE if n is None else n
    if isinstance(v, Err):
        return v
    return VALUE


def num_to_text(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.15g}"


def to_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, Err):
        return v.code
    return num_to_text(v)


def to_bool(v):
    """True / False for a value, or an Err."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if v is None:
        return False
    if isinstance(v, str):
        u = v.strip().upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        return VALUE
    return v if isinstance(v, Err) else VALUE


def final(v):
    """What a cell shows for the result of its formula."""
    if isinstance(v, Arr):
        v = v.rows[0][0] if v.rows and v.rows[0] else VALUE
    if v is None:
        return 0.0
    if isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v


# ------------------------------------------------------------------------------------------------------------------ array helpers
def elem(a, i, j):
    """Element (i, j) of a value that may be an Arr or a scalar (a scalar is the same everywhere; a size-1 dimension repeats)."""
    if not isinstance(a, Arr):
        return a
    rows = a.rows
    r = len(rows)
    c = len(rows[0]) if r else 0
    ii = 0 if r == 1 else i
    jj = 0 if c == 1 else j
    if ii >= r or jj >= c:
        return NA
    return rows[ii][jj]


def map_n(f, *vals):
    """f over scalars, or over the arrays (broadcast like Excel) when one of the values is an Arr."""
    if not any(isinstance(v, Arr) for v in vals):
        return f(*vals)
    R = C = 1
    for v in vals:
        if isinstance(v, Arr):
            r, c = v.shape
            R, C = max(R, r), max(C, c)
    return Arr([[f(*[elem(v, i, j) for v in vals]) for j in range(C)] for i in range(R)])


# ------------------------------------------------------------------------------------------------------------------ operators
def _arith(op, a, b):
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    x = to_num(a)
    if isinstance(x, Err):
        return x
    y = to_num(b)
    if isinstance(y, Err):
        return y
    try:
        if op == "+":
            r = x + y
        elif op == "-":
            r = x - y
        elif op == "*":
            r = x * y
        elif op == "/":
            if y == 0:
                return DIV0
            r = x / y
        else:                                              # ^
            if x == 0 and y == 0:
                return NUM
            if x == 0 and y < 0:
                return DIV0
            if x < 0 and y != int(y):
                return NUM
            r = x ** y
    except OverflowError:
        return NUM
    except ZeroDivisionError:
        return DIV0
    if isinstance(r, complex) or r != r or r in (math.inf, -math.inf):
        return NUM
    return r


def _rank(v):
    return 2 if isinstance(v, bool) else (1 if isinstance(v, str) else 0)


def _compare(op, a, b):
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    if a is None and b is None:
        a = b = 0.0
    elif a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0.0)
    elif b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0.0)
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        c = -1 if ra < rb else 1
    elif ra == 1:
        x, y = a.casefold(), b.casefold()
        c = (x > y) - (x < y)
    else:
        x, y = float(a), float(b)
        c = (x > y) - (x < y)
    return {"=": c == 0, "<>": c != 0, "<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op]


def _concat(a, b):
    if isinstance(a, Err):
        return a
    if isinstance(b, Err):
        return b
    return to_text(a) + to_text(b)


def binop(op, a, b):
    if op in "+-*/^" and len(op) == 1:
        f = lambda x, y: _arith(op, x, y)
    elif op == "&":
        f = _concat
    else:
        f = lambda x, y: _compare(op, x, y)
    return map_n(f, a, b)


def _neg(v):
    if isinstance(v, Err):
        return v
    n = to_num(v)
    return n if isinstance(n, Err) else -n


# ------------------------------------------------------------------------------------------------------------------ the functions
class Func:
    """kind: 'scalar' (one result per value; arrays are worked through element by element), 'agg' (gets the values as they are, ranges as Arr),
    'lazy' (gets ev and the unevaluated nodes: IF, IFERROR, ROW ...).  A function may call ctx.warn(text) to mark its cell."""
    __slots__ = ("name", "fn", "kind", "lo", "hi", "summary", "args", "pack", "ctx")

    def __init__(self, name, fn, kind="scalar", lo=0, hi=None, summary="", args=(), pack=None, ctx=False):
        self.name, self.fn, self.kind, self.lo, self.hi = name, fn, kind, lo, hi
        self.summary, self.args, self.pack, self.ctx = summary, tuple(args), pack, ctx


FUNCS = {}


def register(name, fn, kind="scalar", lo=0, hi=None, summary="", args=(), pack=None, ctx=False):
    """Adds a function.  args: ((name, hint[, optional]) ...) for the Function Arguments window and the help line.  hi=None: any number of arguments."""
    FUNCS[name.upper()] = Func(name.upper(), fn, kind, lo, hi, summary, args, pack, ctx)


def call(name, args, ctx, nodes=None, ev=None):
    f = FUNCS.get(name)
    if f is None:
        return NAME
    n = len(args) if nodes is None else len(nodes)
    if n < f.lo or (f.hi is not None and n > f.hi):
        return VALUE
    if f.kind == "lazy":
        return f.fn(ev, ctx, nodes)
    if f.kind == "agg":
        return f.fn(ctx, *args) if f.ctx else f.fn(*args)
    # scalar: Excel works an array through element by element
    if f.ctx:
        return map_n(lambda *xs: f.fn(ctx, *xs), *args) if args else f.fn(ctx)
    return map_n(f.fn, *args) if args else f.fn()


# ------------------------------------------------------------------------------------------------------------------ the evaluator
def ref_block(t, ctx):
    """The values of a reference: a scalar for one cell, an Arr for a range (a whole column / row is cut to the cells in use)."""
    sh = t.sheet or ctx.sheet
    if t.kind == "cell":
        return ctx.value(sh, t.r1, t.c1)
    r1, c1, r2, c2 = t.rect()
    if t.kind in ("col", "row") or r2 - r1 > 100000 or c2 - c1 > 2000:
        mr, mc = ctx.extent(sh)
        r2, c2 = min(r2, max(mr, r1)), min(c2, max(mc, c1))
    return Arr([[ctx.value(sh, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)])


def evaluate(node, ctx):
    k = node[0]
    if k == "ref":
        return ref_block(node[1], ctx)
    if k == "num":
        return node[1]
    if k == "bin":
        return binop(node[1], evaluate(node[2], ctx), evaluate(node[3], ctx))
    if k == "call":
        f = FUNCS.get(node[1])
        if f is None:
            return NAME
        if f.kind == "lazy":
            return call(node[1], None, ctx, node[2], lambda n: evaluate(n, ctx))
        args = [None if a[0] == "empty" else evaluate(a, ctx) for a in node[2]]
        return call(node[1], args, ctx)
    if k == "str":
        return node[1]
    if k == "bool":
        return node[1]
    if k == "err":
        return node[1]
    if k == "un":
        return map_n(_neg, evaluate(node[2], ctx))
    if k == "pct":
        return map_n(lambda v: v if isinstance(v, Err) else (lambda n: n if isinstance(n, Err) else n / 100.0)(to_num(v)), evaluate(node[1], ctx))
    if k == "name":
        t = ctx.name_target(node[1])
        if t is None:
            return NAME
        return evaluate(t, ctx)
    if k == "arr":
        return Arr([[evaluate(x, ctx) for x in row] for row in node[1]])
    if k == "empty":
        return None
    return VALUE


def run(text, ctx):
    """The value a cell shows for the formula `text`: parse, evaluate, and turn the result into a single value.  A formula that cannot be read is #NAME?."""
    try:
        p = parse(text)
    except FormulaError:
        return NAME
    try:
        return final(evaluate(p.ast, ctx))
    except RecursionError:
        return VALUE
    except (ArithmeticError, ValueError, TypeError, IndexError):
        return VALUE


# ------------------------------------------------------------------------------------------------------------------ copying and editing formulas
def _rewrite(text, fn):
    """The formula text with every reference token replaced by fn(RefTok) -> text (None leaves it alone)."""
    body = text[1:] if text.startswith("=") else text
    lead = text[:1] if text.startswith("=") else ""
    try:
        toks = tokenize(body)
    except FormulaError:
        return text
    out, pos = [], 0
    for kind, tx, s, e, val in toks:
        if kind != "ref":
            continue
        new = fn(val)
        if new is None or new == tx:
            continue
        out.append(body[pos:s])
        out.append(new)
        pos = e
    out.append(body[pos:])
    return lead + "".join(out)


def _shifted(t, dr, dc):
    n = t.copy()
    if not n.ar1:
        n.r1 += dr
    if not n.ar2:
        n.r2 += dr
    if not n.ac1:
        n.c1 += dc
    if not n.ac2:
        n.c2 += dc
    if not (1 <= n.r1 <= MAXROW and 1 <= n.r2 <= MAXROW and 1 <= n.c1 <= MAXCOL and 1 <= n.c2 <= MAXCOL):
        return "#REF!"
    return n.text()


def shift_formula(text, dr, dc):
    """The formula as it reads when copied `dr` rows down and `dc` columns right: references without $ move, references with $ stay."""
    if not (isinstance(text, str) and text.startswith("=")) or (dr == 0 and dc == 0):
        return text
    return _rewrite(text, lambda t: _shifted(t, dr, dc))


def adjust_formula(text, formula_sheet, target_sheet, axis, at, n):
    """The formula after `n` rows (axis 'r') or columns (axis 'c') were inserted before index `at` (n > 0) or deleted from `at` (n < 0) in target_sheet."""
    if not (isinstance(text, str) and text.startswith("=")):
        return text

    def one(t):
        if (t.sheet or formula_sheet) != target_sheet:
            return None
        n2 = t.copy()
        lo, hi = ("r1", "r2") if axis == "r" else ("c1", "c2")
        a, b = getattr(n2, lo), getattr(n2, hi)
        if t.kind == "col" and axis == "r" or t.kind == "row" and axis == "c":
            return None
        if n > 0:
            if a >= at:
                a += n
            if b >= at:
                b += n
        else:
            k = -n
            end = at + k - 1
            if a >= at and b <= end:
                return "#REF!"
            if a > end:
                a -= k
            elif a >= at:
                a = at
            if b > end:
                b -= k
            elif b >= at:
                b = at - 1
            if a > b:
                return "#REF!"
        setattr(n2, lo, a)
        setattr(n2, hi, b)
        return n2.text()
    return _rewrite(text, one)


def rename_sheet(text, old, new):
    """The formula with the sheet name `old` replaced by `new` in every reference that names it."""
    if not (isinstance(text, str) and text.startswith("=")):
        return text

    def one(t):
        if t.prefix and t.sheet == old:
            n2 = t.copy()
            n2.prefix = quote_sheet(new) + "!"
            return n2.text()
        return None
    return _rewrite(text, one)


def sheet_removed(text, name):
    """The formula with every reference to the deleted sheet `name` turned into #REF!."""
    if not (isinstance(text, str) and text.startswith("=")):
        return text
    return _rewrite(text, lambda t: "#REF!" if t.prefix and t.sheet == name else None)


def qualify(text, sheet):
    """The formula with every reference that names no sheet given the sheet `sheet` (so it can be moved to another sheet and still mean the same)."""
    if not (isinstance(text, str) and text.startswith("=")):
        return text

    def one(t):
        if t.prefix:
            return None
        n2 = t.copy()
        n2.prefix = quote_sheet(sheet) + "!"
        return n2.text()
    return _rewrite(text, one)


def refs_in(text):
    """The reference tokens of a formula (empty for text that is not a formula or cannot be read)."""
    try:
        return list(parse(text).refs)
    except FormulaError:
        return []


def function_at(text, pos):
    """(function name, index of the argument the cursor `pos` is in, the argument texts) for the innermost function call around `pos` in a formula being
    typed; None when the cursor is not inside a call.  Works on unfinished formulas (no closing bracket yet)."""
    body = text[1:] if text.startswith("=") else text
    off = 1 if text.startswith("=") else 0
    p = max(0, pos - off)
    try:
        toks = tokenize(body[:p])
    except FormulaError:
        return None
    stack = []
    skip_lp = False
    for kind, tx, s, e, val in toks:
        if kind == "func":
            stack.append([val, 0, e + 1, "func"])
            skip_lp = True
        elif kind == "lp":
            if skip_lp:
                skip_lp = False                           # the "(" of the call itself
                continue
            stack.append([None, 0, s + 1, "group"])
        elif kind == "rp":
            if stack:
                stack.pop()
        elif kind == "comma" and stack:
            stack[-1][1] += 1
    for fr in reversed(stack):
        if fr[3] == "func":
            return fr[0], fr[1]
    return None
