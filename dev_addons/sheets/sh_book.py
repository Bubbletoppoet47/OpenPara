"""
sh_book.py - the workbook of Sheets: sheets of cells, formulas that follow their inputs, copy / fill / insert / delete, undo, and the .opsheet file.
No window in it (sh_tab.py is the window).

    wb = Workbook()                        wb.sheets[i].name
    wb.set_input("Sheet1", 4, 2, "=B2*3")  what a person types into a cell (a number, text, or a formula that starts with "=")
    wb.value("Sheet1", 4, 2)               the value now (float, str, bool, None, Err)
    wb.display("Sheet1", 4, 2)             the text the cell shows
    wb.begin("Paste"); ...; wb.end()       one undo step for everything between;  wb.undo() / wb.redo()
    wb.to_json() / Workbook.from_json(d)   the file

A formula that is changed makes the cells that use it work themselves out again, in an order where every cell is calculated after the cells it reads
(no deep recursion: a column of 10 000 running totals is fine).  A cell that reads itself shows #CIRC!.
"""
import copy
import json
import re
from collections import namedtuple

import sh_engine as E
import sh_fmt
import sh_funcs  # noqa: F401  (adds the functions)

FORMAT = "openpara-sheets"
UNDO_LIMIT = 100

Style = namedtuple("Style", "fmt bold italic fg bg align")
DEFAULT_STYLE = Style("General", False, False, None, None, None)
_STYLES = {}


def style_of(**kw):
    """An (interned) Style: the default with the given parts changed."""
    return intern_style(DEFAULT_STYLE._replace(**kw))


def intern_style(s):
    if s is None or s == DEFAULT_STYLE:
        return None
    return _STYLES.setdefault(s, s)


class Cell:
    __slots__ = ("raw", "value", "st", "dirty", "arr", "rects")

    def __init__(self, raw=None, st=None):
        self.raw, self.value, self.st = raw, raw, st
        self.dirty, self.arr, self.rects = False, False, None

    @property
    def is_formula(self):
        return isinstance(self.raw, str) and self.raw.startswith("=") and len(self.raw) > 1 and not self.raw.startswith("'")

    @property
    def fmt(self):
        return self.st.fmt if self.st else "General"


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}
        self.col_w = {}
        self.row_h = {}
        self.names = {}               # names that belong to this sheet: {NAME: "=Sheet1!$B$2"}
        self.charts = []              # chart definitions (sh_chart.py)
        self.links = []               # imported studies (sh_study.py)
        self.freeze = None            # (rows, cols) kept on screen
        self._ext = None

    def used(self):
        """(last row, last column) that hold anything."""
        if self._ext is None:
            mr = mc = 0
            for (r, c), cell in self.cells.items():
                if cell.raw is not None or cell.st is not None:
                    mr, mc = max(mr, r), max(mc, c)
            self._ext = (mr, mc)
        return self._ext

    def touched(self, r, c):
        if self._ext is not None:
            self._ext = (max(self._ext[0], r), max(self._ext[1], c))


def parse_entry(text):
    """What a person typed -> (raw, format hint).  Numbers become floats, TRUE / FALSE become booleans, '=...' stays a formula, '...' is text."""
    if text is None:
        return None, None
    if not isinstance(text, str):
        return text, None
    if text == "":
        return None, None
    if text.startswith("=") and len(text) > 1:
        return text, None
    if text.startswith("'"):
        return text, None
    t = text.strip()
    u = t.upper()
    if u == "TRUE":
        return True, None
    if u == "FALSE":
        return False, None
    n = E.str_to_num(t)
    if n is not None and re.match(r"^[+-]?[\d.,]+(?:[eE][+-]?\d+)?%?$", t):
        return n, ("0%" if t.endswith("%") else None)
    return text, None


def plain(raw):
    """The value of a cell that holds no formula: text that starts with ' is that text without the '."""
    return raw[1:] if isinstance(raw, str) and raw.startswith("'") else raw


def edit_text(cell):
    """The text the cell editor starts with."""
    if cell is None or cell.raw is None:
        return ""
    r = cell.raw
    if isinstance(r, bool):
        return "TRUE" if r else "FALSE"
    if isinstance(r, float):
        s = E.num_to_text(r)
        return s
    return str(r)


class Workbook:
    def __init__(self, with_sheet=True):
        self.sheets = []
        self.names = {}
        self.active = 0
        self.listeners = []
        self._group = None
        self.warnings = {}
        self.rev = {}                 # (sheet, column) -> {cell key: [(row1, row2)]}   who reads a run of cells (A1:A9)
        self.pts = {}                 # (sheet, column, row) -> {cell keys}             who reads one cell (A1) - the usual case, found at once
        self.wide = {}                # sheet -> {cell key: [(r1, c1, r2, c2)]}          readers of very wide ranges
        self.dirty = {}               # sheet -> {(r, c)}
        self.sheet = None
        self.row = self.col = 0
        self._warn = None
        self._tx = None
        self._undo, self._redo = [], []
        self._silent = 0
        self._changed = set()
        self.version = 0
        if with_sheet:
            self.add_sheet("Sheet1")

    # ------------------------------------------------------------------------------------------------ sheets
    def sheet_names(self):
        return [s.name for s in self.sheets]

    def get_sheet(self, name):
        for s in self.sheets:
            if s.name == name:
                return s
        for s in self.sheets:
            if s.name.casefold() == str(name).casefold():
                return s
        return None

    def unique_name(self, base):
        names = {s.name.casefold() for s in self.sheets}
        if base.casefold() not in names:
            return base
        i = 2
        while f"{base} ({i})".casefold() in names:
            i += 1
        return f"{base} ({i})"

    def add_sheet(self, name=None, index=None):
        name = self.unique_name(name or f"Sheet{len(self.sheets) + 1}")
        s = Sheet(name)
        if index is None:
            self.sheets.append(s)
        else:
            self.sheets.insert(index, s)
        self._structure()
        return s

    @staticmethod
    def valid_sheet_name(name):
        return bool(name) and len(name) <= 31 and not re.search(r"[\[\]:*?/\\]", name) and not name.startswith("'") and not name.endswith("'")

    def rename_sheet(self, old, new):
        s = self.get_sheet(old)
        if s is None or not self.valid_sheet_name(new) or (self.get_sheet(new) not in (None, s)):
            return False
        self._snapshot_begin(f"Rename sheet {old}")
        s.name = new
        for sh in self.sheets:
            for (r, c), cell in sh.cells.items():
                if cell.is_formula:
                    cell.raw = E.rename_sheet(cell.raw, old, new)
            for ch in sh.charts:
                _map_chart_refs(ch, lambda t: E.rename_sheet("=" + t, old, new)[1:])
            for k, v in list(sh.names.items()):
                sh.names[k] = E.rename_sheet(v, old, new)
            for ln in sh.links:
                pass
        for k, v in list(self.names.items()):
            self.names[k] = E.rename_sheet(v, old, new)
        self._rebuild_all()
        self._snapshot_end()
        return True

    def delete_sheet(self, name):
        s = self.get_sheet(name)
        if s is None or len(self.sheets) <= 1:
            return False
        self._snapshot_begin(f"Delete sheet {name}")
        i = self.sheets.index(s)
        self.sheets.remove(s)
        for sh in self.sheets:
            for cell in sh.cells.values():
                if cell.is_formula:
                    cell.raw = E.sheet_removed(cell.raw, name)
            sh.charts = [ch for ch in sh.charts if not _chart_uses(ch, name)]
        self.active = min(self.active, len(self.sheets) - 1)
        self._rebuild_all()
        self._snapshot_end()
        return True

    def duplicate_sheet(self, name):
        s = self.get_sheet(name)
        if s is None:
            return None
        self._snapshot_begin(f"Copy sheet {name}")
        n = self.add_sheet(self.unique_name(name + " (2)"), self.sheets.index(s) + 1)
        for k, cell in s.cells.items():
            c2 = Cell(cell.raw, cell.st)
            c2.arr = cell.arr
            n.cells[k] = c2
        n.col_w, n.row_h, n.freeze = dict(s.col_w), dict(s.row_h), s.freeze
        n.names = {k: v for k, v in s.names.items()}
        n.charts = copy.deepcopy(s.charts)
        for ch in n.charts:
            ch["id"] = _new_id(n.charts)
            _map_chart_refs(ch, lambda t: E.rename_sheet("=" + t, name, n.name)[1:])
        self._rebuild_all()
        self._snapshot_end()
        return n

    def move_sheet(self, name, index):
        s = self.get_sheet(name)
        if s is None:
            return
        self.sheets.remove(s)
        self.sheets.insert(max(0, min(index, len(self.sheets))), s)
        self._structure()

    # ------------------------------------------------------------------------------------------------ reading
    def cell(self, sheet, r, c):
        s = self.get_sheet(sheet)
        return s.cells.get((r, c)) if s else None

    def value(self, sheet, r, c):
        s = self.get_sheet(sheet)
        if s is None:
            return E.REF
        cell = s.cells.get((r, c))
        if cell is None:
            return None
        if cell.dirty:
            self._compute(sheet, r, c)
        return cell.value

    def extent(self, sheet):
        s = self.get_sheet(sheet)
        return s.used() if s else (0, 0)

    def display(self, sheet, r, c):
        cell = self.cell(sheet, r, c)
        if cell is None:
            return ""
        v = self.value(sheet, r, c)
        if isinstance(cell.raw, str) and cell.raw.startswith("'") and not cell.is_formula:
            return cell.raw[1:]
        return sh_fmt.show(v, cell.fmt)

    def name_target(self, name):
        sh = self.get_sheet(self.sheet)
        key = None
        for k in (sh.names if sh else {}):
            if k.casefold() == name.casefold():
                key = (sh.names, k)
        if key is None:
            for k in self.names:
                if k.casefold() == name.casefold():
                    key = (self.names, k)
        if key is None:
            return None
        try:
            return E.parse(key[0][key[1]]).ast
        except E.FormulaError:
            return None

    def warn(self, text):
        if self._warn is not None and text not in self._warn:
            self._warn.append(text)

    def evaluate(self, text, sheet=None, r=1, c=1, raw=False, warnings=None):
        """The value of a formula text worked out as if it stood in the cell (sheet, r, c), without putting it there (None for a formula that cannot be read).
        warnings: a list that gets the warning texts the formula raised."""
        sheet = sheet or self.sheets[self.active].name
        sv = (self.sheet, self.row, self.col, self._warn)
        self.sheet, self.row, self.col, self._warn = sheet, r, c, []
        try:
            p = E.parse(text)
            v = E.evaluate(p.ast, self)
            return v if raw else E.final(v)
        except E.FormulaError:
            return None
        except (ArithmeticError, ValueError, TypeError, IndexError, RecursionError):
            return E.VALUE
        finally:
            if warnings is not None:
                warnings.extend(self._warn or [])
            self.sheet, self.row, self.col, self._warn = sv

    # ------------------------------------------------------------------------------------------------ writing one cell
    def _get_or_make(self, s, r, c):
        cell = s.cells.get((r, c))
        if cell is None:
            cell = s.cells[(r, c)] = Cell()
        return cell

    def _record(self, sheet, r, c):
        if self._tx is None:
            return
        k = (sheet, r, c)
        if k not in self._tx["before"]:
            cell = self.cell(sheet, r, c)
            self._tx["before"][k] = (cell.raw, cell.st, cell.arr) if cell else None

    def _put(self, sheet, r, c, raw, st=..., arr=False, record=True):
        """Sets raw (and style when given) of a cell, keeps the dependency index right and queues the recalculation.  Does not recalculate yet."""
        s = self.get_sheet(sheet)
        if s is None:
            return
        if record:
            self._record(sheet, r, c)
        cell = s.cells.get((r, c))
        key = (sheet, r, c)
        if cell is not None and cell.is_formula:
            self._unregister(key, cell)
        if cell is None:
            if raw is None and (st is ... or st is None):
                return
            cell = s.cells[(r, c)] = Cell()
        cell.raw = raw
        cell.arr = arr
        if st is not ...:
            cell.st = st
        if raw is None and cell.st is None:
            s.cells.pop((r, c), None)
            s._ext = None
            self.warnings.pop(key, None)
            self._dirty_dependents(key)
            self.dirty.get(sheet, set()).discard((r, c))
            self._changed.add(key)
            return
        s.touched(r, c)
        if cell.is_formula:
            self._register(key, cell)
            cell.dirty = True
            self.dirty.setdefault(sheet, set()).add((r, c))
        else:
            cell.value = plain(raw)
            cell.dirty = False
            self.dirty.get(sheet, set()).discard((r, c))
            self.warnings.pop(key, None)
        self._dirty_dependents(key)
        self._changed.add(key)

    # ------------------------------------------------------------------------------------------------ dependencies
    def _rects_of(self, sheet, cell):
        out = []
        try:
            p = E.parse(cell.raw)
        except E.FormulaError:
            return out
        for t in p.refs:
            sh = t.sheet or sheet
            r1, c1, r2, c2 = t.rect()
            out.append((sh, r1, c1, r2, c2))
        for nm in p.names:
            t = self._name_ast(sheet, nm)
            if t is not None:
                self._ast_rects(t, sheet, out)
        return out

    def _name_ast(self, sheet, nm):
        sv = self.sheet
        self.sheet = sheet
        try:
            return self.name_target(nm)
        finally:
            self.sheet = sv

    def _ast_rects(self, node, sheet, out):
        if node[0] == "ref":
            t = node[1]
            r1, c1, r2, c2 = t.rect()
            out.append((t.sheet or sheet, r1, c1, r2, c2))
        elif node[0] == "bin":
            self._ast_rects(node[2], sheet, out)
            self._ast_rects(node[3], sheet, out)

    def _register(self, key, cell):
        sheet = key[0]
        cell.rects = self._rects_of(sheet, cell)
        by_col = {}
        for sh, r1, c1, r2, c2 in cell.rects:
            if c2 - c1 > 256:
                self.wide.setdefault(sh, {}).setdefault(key, []).append((r1, c1, r2, c2))
                continue
            for c in range(c1, c2 + 1):
                if r1 == r2:
                    self.pts.setdefault((sh, c, r1), set()).add(key)
                else:
                    by_col.setdefault((sh, c), []).append((r1, r2))
        for bk, rr in by_col.items():
            self.rev.setdefault(bk, {})[key] = rr

    def _unregister(self, key, cell):
        for sh, r1, c1, r2, c2 in (cell.rects or ()):
            if c2 - c1 > 256:
                w = self.wide.get(sh)
                if w:
                    w.pop(key, None)
                continue
            for c in range(c1, c2 + 1):
                if r1 == r2:
                    p = self.pts.get((sh, c, r1))
                    if p:
                        p.discard(key)
                        if not p:
                            del self.pts[(sh, c, r1)]
                    continue
                b = self.rev.get((sh, c))
                if b:
                    b.pop(key, None)
        cell.rects = None

    def _readers(self, sheet, r, c):
        """The formula cells that read the cell (sheet, r, c)."""
        out = list(self.pts.get((sheet, c, r), ()))
        b = self.rev.get((sheet, c))
        if b:
            for k, rr in b.items():
                for r1, r2 in rr:
                    if r1 <= r <= r2:
                        out.append(k)
                        break
        w = self.wide.get(sheet)
        if w:
            for k, rects in w.items():
                for r1, c1, r2, c2 in rects:
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        out.append(k)
                        break
        return out

    def _dirty_dependents(self, key):
        """Marks every formula cell that (directly or through others) reads `key` as needing work."""
        stack = [key]
        seen = set()
        while stack:
            sh, r, c = stack.pop()
            for k in self._readers(sh, r, c):
                if k in seen:
                    continue
                seen.add(k)
                cell = self.cell(*k)
                if cell is None or not cell.is_formula:
                    continue
                cell.dirty = True
                self.dirty.setdefault(k[0], set()).add((k[1], k[2]))
                self._changed.add(k)
                stack.append(k)

    def _precedents_dirty(self, key, cell):
        out = []
        for sh, r1, c1, r2, c2 in (cell.rects or ()):
            d = self.dirty.get(sh)
            if not d:
                continue
            area = (r2 - r1 + 1) * (c2 - c1 + 1)
            if area <= len(d):
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        if (r, c) in d:
                            out.append((sh, r, c))
            else:
                for (r, c) in d:
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        out.append((sh, r, c))
        return out

    def _compute(self, sheet, r, c):
        cell = self.cell(sheet, r, c)
        sv = (self.sheet, self.row, self.col, self._warn)
        self.sheet, self.row, self.col, self._warn = sheet, r, c, []
        try:
            cell.value = E.run(cell.raw, self)
            w = self._warn
        finally:
            self.sheet, self.row, self.col, self._warn = sv
        key = (sheet, r, c)
        if w:
            self.warnings[key] = w
        else:
            self.warnings.pop(key, None)
        cell.dirty = False
        self.dirty.get(sheet, set()).discard((r, c))

    def recalc(self):
        """Works out every cell that is out of date, each after the cells it reads.  Cells that read each other in a loop all show #CIRC! (whatever order they
        are found in); cells that only read a loop get the error through their formula."""
        while True:
            todo = [(sh, r, c) for sh, d in self.dirty.items() for (r, c) in d]
            if not todo:
                return
            index, low, on_stack, stack, loops = {}, {}, set(), [], set()
            n = 0
            for start in todo:
                cs = self.cell(*start)
                if start in index or cs is None or not cs.dirty:
                    continue
                index[start] = low[start] = n
                n += 1
                stack.append(start)
                on_stack.add(start)
                work = [(start, iter(self._deps(start, loops)))]
                while work:
                    k, it = work[-1]
                    pushed = False
                    for p in it:
                        if p not in index:
                            index[p] = low[p] = n
                            n += 1
                            stack.append(p)
                            on_stack.add(p)
                            work.append((p, iter(self._deps(p, loops))))
                            pushed = True
                            break
                        if p in on_stack:
                            low[k] = min(low[k], index[p])
                    if pushed:
                        continue
                    work.pop()
                    if work:
                        low[work[-1][0]] = min(low[work[-1][0]], low[k])
                    if low[k] == index[k]:                           # k closes a group of cells that depend on each other (usually just k)
                        group = []
                        while True:
                            w = stack.pop()
                            on_stack.discard(w)
                            group.append(w)
                            if w == k:
                                break
                        if len(group) > 1 or k in loops:
                            for sh, r, c in group:
                                cell = self.cell(sh, r, c)
                                cell.value = E.CIRC
                                cell.dirty = False
                                self.dirty.get(sh, set()).discard((r, c))
                                self.warnings.pop((sh, r, c), None)
                        else:
                            self._compute(*k)
            for sh in list(self.dirty):
                if not self.dirty[sh]:
                    del self.dirty[sh]

    def _deps(self, key, loops):
        """The out-of-date cells that the formula at `key` reads (a cell that reads itself is noted in `loops`)."""
        cell = self.cell(*key)
        out = self._precedents_dirty(key, cell)
        if key in out:
            loops.add(key)
        return out

    # ------------------------------------------------------------------------------------------------ undo
    def begin(self, label="Edit"):
        if self._tx is None:
            self._tx = {"label": label, "before": {}, "depth": 1}
        else:
            self._tx["depth"] += 1

    def end(self):
        tx = self._tx
        if tx is None:
            return set()
        tx["depth"] -= 1
        if tx["depth"] > 0:
            return set()
        self._tx = None
        changed = self._flush()
        if tx["before"]:
            after = {}
            for k in tx["before"]:
                cell = self.cell(*k)
                after[k] = (cell.raw, cell.st, cell.arr) if cell else None
            if after != tx["before"]:
                self._undo.append(("cells", tx["label"], tx["before"], after))
                self._undo[:] = self._undo[-UNDO_LIMIT:]
                self._redo.clear()
        return changed

    def _flush(self):
        self.recalc()
        changed, self._changed = self._changed, set()
        if changed:
            self.version += 1
            self._notify(changed, False)
        return changed

    def _notify(self, changed, structure):
        for fn in list(self.listeners):
            try:
                fn(changed, structure)
            except RuntimeError:
                pass

    def _structure(self):
        self.version += 1
        self._notify(set(), True)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo_label(self):
        return self._undo[-1][1] if self._undo else ""

    def redo_label(self):
        return self._redo[-1][1] if self._redo else ""

    def _apply(self, states):
        self._tx = None
        for (sh, r, c), st in states.items():
            if st is None:
                self._put(sh, r, c, None, None, record=False)
            else:
                self._put(sh, r, c, st[0], st[1], st[2], record=False)
        return self._flush()

    def undo(self):
        if not self._undo:
            return False
        e = self._undo.pop()
        if e[0] == "cells":
            self._apply(e[2])
        else:
            self._load_state(e[2])
        self._redo.append(e)
        return True

    def redo(self):
        if not self._redo:
            return False
        e = self._redo.pop()
        if e[0] == "cells":
            self._apply(e[3])
        else:
            self._load_state(e[3])
        self._undo.append(e)
        return True

    def begin_group(self, label):
        """Everything done until end_group() is ONE undo step (even inserted columns and changes to the sheets' links); nests."""
        if self._group is None:
            self._group = [label, self.to_json(), list(self._undo), 0]
        self._group[3] += 1

    def end_group(self):
        g = self._group
        if g is None:
            return
        g[3] -= 1
        if g[3] > 0:
            return
        self._group = None
        label, before, steps, _d = g
        after = self.to_json()
        self._undo[:] = (steps + ([("snap", label, before, after)] if after != before else []))[-UNDO_LIMIT:]
        if after != before:
            self._redo.clear()

    def _snapshot_begin(self, label):
        self._snap = (label, self.to_json())

    def _snapshot_end(self):
        label, before = self._snap
        self._snap = None
        self._undo.append(("snap", label, before, self.to_json()))
        self._undo[:] = self._undo[-UNDO_LIMIT:]
        self._redo.clear()
        self._flush()
        self._structure()

    def _load_state(self, d):
        keep = (self.listeners, self._undo, self._redo, self.active)
        self._read_json(d)
        self.listeners, self._undo, self._redo = keep[0], keep[1], keep[2]
        self.active = max(0, min(keep[3], len(self.sheets) - 1))
        self._structure()

    # ------------------------------------------------------------------------------------------------ the editing operations
    def set_input(self, sheet, r, c, text, undo=True, label=None):
        """A person types `text` into a cell."""
        raw, hint = parse_entry(text)
        self.begin(label or "Edit cell")
        s = self.get_sheet(sheet)
        cell = s.cells.get((r, c)) if s else None
        st = ...
        if hint and (cell is None or cell.fmt in ("General", None)):
            st = style_of(fmt=hint) if not (cell and cell.st) else intern_style(cell.st._replace(fmt=hint))
        self._put(sheet, r, c, raw, st)
        return self.end()

    def set_raw(self, sheet, r, c, raw, st=...):
        """Like set_input but with a ready value (inside begin / end)."""
        self._put(sheet, r, c, raw, st)

    def clear(self, sheet, rect, styles=False):
        r1, c1, r2, c2 = rect
        s = self.get_sheet(sheet)
        self.begin("Clear")
        for (r, c) in [k for k in s.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
            self._put(sheet, r, c, None, None if styles else ...)
        return self.end()

    def set_style(self, sheet, rect, **kw):
        """Changes parts of the style (fmt, bold, italic, fg, bg, align) of every cell of the rectangle."""
        r1, c1, r2, c2 = rect
        s = self.get_sheet(sheet)
        self.begin("Format")
        n = (r2 - r1 + 1) * (c2 - c1 + 1)
        if n > 200000:
            r2 = min(r2, r1 + 1000)
            c2 = min(c2, c1 + 200)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = s.cells.get((r, c))
                base = cell.st if cell and cell.st else DEFAULT_STYLE
                st = intern_style(base._replace(**kw))
                if cell is None and st is None:
                    continue
                self._put(sheet, r, c, cell.raw if cell else None, st, arr=cell.arr if cell else False)
        return self.end()

    def copy_cells(self, src_sheet, src_rect, dst_sheet, dst_r, dst_c, what="all", cut=False):
        """Copies a block like Excel: formulas move their relative references with the block.  what: all | values | formulas | formats.  cut=True moves the
        block (its formulas keep pointing at the same cells).  Joins the caller's begin / end, or makes its own undo step.  Returns the destination rectangle."""
        r1, c1, r2, c2 = src_rect
        s = self.get_sheet(src_sheet)
        block = {}
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell = s.cells.get((r, c))
                block[(r - r1, c - c1)] = None if cell is None else (cell.raw, cell.st, cell.arr, self.value(src_sheet, r, c))
        own = self._tx is None
        if own:
            self.begin("Cut" if cut else "Paste")
        if cut:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    self._put(src_sheet, r, c, None, None)
        for (i, j), item in block.items():
            r, c = dst_r + i, dst_c + j
            if r > E.MAXROW or c > E.MAXCOL:
                continue
            old = self.cell(dst_sheet, r, c)
            if item is None:
                if what == "all":
                    self._put(dst_sheet, r, c, None, None)
                elif what in ("values", "formulas"):
                    self._put(dst_sheet, r, c, None)
                continue
            raw, st, arr, val = item
            if what == "formats":
                self._put(dst_sheet, r, c, old.raw if old else None, st, arr=old.arr if old else False)
                continue
            if isinstance(raw, str) and raw.startswith("=") and len(raw) > 1:
                if what == "values":
                    raw = None if isinstance(val, E.Err) else val
                    arr = False
                elif cut:
                    raw = _moved(raw, src_sheet, dst_sheet)
                else:
                    raw = E.shift_formula(raw, r - (r1 + i), c - (c1 + j))
            if what == "all":
                self._put(dst_sheet, r, c, raw, st, arr=arr if isinstance(raw, str) and raw.startswith("=") else False)
            else:
                self._put(dst_sheet, r, c, raw, ..., arr=arr and what == "formulas")
        rect = (dst_r, dst_c, dst_r + r2 - r1, dst_c + c2 - c1)
        if own:
            self.end()
        return rect

    def fill(self, sheet, src_rect, dst_rect):
        """Fills dst_rect (next to src_rect, in line with it) from src_rect, like dragging the fill handle: formulas are copied with their references moved,
        two or more numbers in a row / column continue as a series, anything else repeats."""
        r1, c1, r2, c2 = src_rect
        d1, e1, d2, e2 = dst_rect
        s = self.get_sheet(sheet)
        vertical = d1 > r2 or d2 < r1
        self.begin("Fill")
        if vertical:
            for c in range(c1, c2 + 1):
                col = [s.cells.get((r, c)) for r in range(r1, r2 + 1)]
                nums = [x.raw for x in col if x is not None and isinstance(x.raw, float)]
                series = len(col) >= 2 and len(nums) == len(col)
                step = (nums[-1] - nums[0]) / (len(nums) - 1) if series else 0.0
                for r in range(d1, d2 + 1):
                    k = (r - r1) % len(col)
                    if series:
                        self._put(sheet, r, c, nums[0] + step * (r - r1), col[k].st)
                    else:
                        self._copy_one(col[k], r1 + k, c, r, c, sheet)
        else:
            for r in range(r1, r2 + 1):
                row = [s.cells.get((r, c)) for c in range(c1, c2 + 1)]
                nums = [x.raw for x in row if x is not None and isinstance(x.raw, float)]
                series = len(row) >= 2 and len(nums) == len(row)
                step = (nums[-1] - nums[0]) / (len(nums) - 1) if series else 0.0
                for c in range(e1, e2 + 1):
                    k = (c - c1) % len(row)
                    if series:
                        self._put(sheet, r, c, nums[0] + step * (c - c1), row[k].st)
                    else:
                        self._copy_one(row[k], r, c1 + k, r, c, sheet)
        return self.end()

    def _copy_one(self, src, sr, sc, dr, dc, sheet):
        if src is None:
            self._put(sheet, dr, dc, None, None)
            return
        raw = src.raw
        if isinstance(raw, str) and raw.startswith("=") and len(raw) > 1:
            raw = E.shift_formula(raw, dr - sr, dc - sc)
        self._put(sheet, dr, dc, raw, src.st, arr=src.arr)

    def paste_to_sheets(self, src_sheet, src_rect, targets, what="all"):
        """Copies a block to the same place on other sheets (formulas then read the cells of the sheet they are pasted on)."""
        r1, c1, r2, c2 = src_rect
        self.begin("Paste to sheets")
        for t in targets:
            if t != src_sheet:
                self.copy_cells(src_sheet, src_rect, t, r1, c1, what)
        return self.end()

    def insert(self, sheet, axis, at, n=1):
        """Inserts n rows (axis 'r') or columns ('c') before index `at`."""
        return self._shift(sheet, axis, at, n)

    def delete(self, sheet, axis, at, n=1):
        return self._shift(sheet, axis, at, -n)

    def _shift(self, sheet, axis, at, n):
        s = self.get_sheet(sheet)
        self._snapshot_begin(("Insert " if n > 0 else "Delete ") + ("rows" if axis == "r" else "columns"))
        i = 0 if axis == "r" else 1
        new = {}
        for k, cell in s.cells.items():
            idx = k[i]
            if n > 0:
                if idx >= at:
                    k = (k[0] + n, k[1]) if axis == "r" else (k[0], k[1] + n)
            else:
                if at <= idx < at - n:
                    continue
                if idx >= at - n:
                    k = (k[0] + n, k[1]) if axis == "r" else (k[0], k[1] + n)
            new[k] = cell
        s.cells = new
        s._ext = None
        dim = s.row_h if axis == "r" else s.col_w
        moved = {}
        for idx, w in dim.items():
            if n > 0:
                moved[idx + n if idx >= at else idx] = w
            elif not (at <= idx < at - n):
                moved[idx + n if idx >= at - n else idx] = w
        dim.clear()
        dim.update(moved)
        for sh in self.sheets:
            for cell in sh.cells.values():
                if cell.is_formula:
                    cell.raw = E.adjust_formula(cell.raw, sh.name, sheet, axis, at, n)
            for ch in sh.charts:
                _map_chart_refs(ch, lambda t, sh=sh: _adjust_ref(t, sh.name, sheet, axis, at, n))
            for k, v in list(sh.names.items()):
                sh.names[k] = E.adjust_formula(v, sh.name, sheet, axis, at, n)
        for k, v in list(self.names.items()):
            self.names[k] = E.adjust_formula(v, self.sheets[0].name, sheet, axis, at, n)
        for ln in s.links:
            o = ln.get("origin")
            if o and axis == "r" and o[0] >= at:
                ln["origin"] = [max(1, o[0] + n), o[1]]
            elif o and axis == "c" and o[1] >= at:
                ln["origin"] = [o[0], max(1, o[1] + n)]
        self._rebuild_all()
        self._snapshot_end()

    # ------------------------------------------------------------------------------------------------ names
    def set_name(self, name, refers_to, sheet=None):
        """Defines a name (for the whole workbook, or only for `sheet`): refers_to is a reference or a formula such as '=Sheet1!$B$6'."""
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*$", name) or E.parse_addr(name):
            return False
        if not refers_to.startswith("="):
            refers_to = "=" + refers_to
        self._snapshot_begin(f"Name {name}")
        (self.get_sheet(sheet).names if sheet else self.names)[name] = refers_to
        self._rebuild_all()
        self._snapshot_end()
        return True

    def delete_name(self, name, sheet=None):
        d = self.get_sheet(sheet).names if sheet else self.names
        if name in d:
            self._snapshot_begin(f"Delete name {name}")
            del d[name]
            self._rebuild_all()
            self._snapshot_end()

    # ------------------------------------------------------------------------------------------------ rebuilding
    def _rebuild_all(self):
        """After a change that touches many formulas: the dependency index again from scratch, and everything worked out again."""
        self.rev, self.pts, self.wide, self.dirty = {}, {}, {}, {}
        self.warnings = {}
        for s in self.sheets:
            s._ext = None
            for (r, c), cell in s.cells.items():
                if cell.is_formula:
                    self._register((s.name, r, c), cell)
                    cell.dirty = True
                    self.dirty.setdefault(s.name, set()).add((r, c))
                else:
                    cell.value = plain(cell.raw)
                    cell.dirty = False
        self._changed.add(("*", 0, 0))

    # ------------------------------------------------------------------------------------------------ the file
    def to_json(self):
        styles, sidx = [], {}
        sheets = []
        for s in self.sheets:
            cells = []
            for (r, c), cell in sorted(s.cells.items()):
                if cell.raw is None and cell.st is None:
                    continue
                item = [r, c, cell.raw]
                if cell.st is not None:
                    if cell.st not in sidx:
                        sidx[cell.st] = len(styles)
                        styles.append(list(cell.st))
                    item.append(sidx[cell.st])
                elif cell.arr:
                    item.append(-1)
                if cell.arr:
                    item.append("a")
                cells.append(item)
            sheets.append({"name": s.name, "cells": cells, "col_w": {str(k): v for k, v in s.col_w.items()}, "row_h": {str(k): v for k, v in s.row_h.items()},
                           "names": dict(s.names), "charts": copy.deepcopy(s.charts), "links": copy.deepcopy(s.links), "freeze": s.freeze})
        return {"format": FORMAT, "version": 1, "active": self.active, "names": dict(self.names), "styles": styles, "sheets": sheets}

    @classmethod
    def from_json(cls, d):
        wb = cls(with_sheet=False)
        wb._read_json(d)
        return wb

    def _read_json(self, d):
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise ValueError("This is not a Sheets file.")
        styles = [intern_style(Style(*x)) if len(x) == 6 else None for x in d.get("styles", [])]
        self.sheets = []
        self.names = dict(d.get("names", {}))
        for sd in d.get("sheets", []):
            s = Sheet(sd["name"])
            for item in sd.get("cells", []):
                r, c, raw = item[0], item[1], item[2]
                if isinstance(raw, int) and not isinstance(raw, bool):
                    raw = float(raw)
                st = styles[item[3]] if len(item) > 3 and isinstance(item[3], int) and 0 <= item[3] < len(styles) else None
                cell = Cell(raw, st)
                cell.arr = len(item) > 4 and item[4] == "a" or (len(item) > 3 and item[3] == "a")
                s.cells[(r, c)] = cell
            s.col_w = {int(k): v for k, v in sd.get("col_w", {}).items()}
            s.row_h = {int(k): v for k, v in sd.get("row_h", {}).items()}
            s.names = dict(sd.get("names", {}))
            s.charts = copy.deepcopy(list(sd.get("charts", [])))
            s.links = copy.deepcopy(list(sd.get("links", [])))
            s.freeze = tuple(sd["freeze"]) if sd.get("freeze") else None
            self.sheets.append(s)
        if not self.sheets:
            self.sheets.append(Sheet("Sheet1"))
        self.active = max(0, min(int(d.get("active", 0)), len(self.sheets) - 1))
        self._rebuild_all()
        self.recalc()
        self._changed.clear()

    def save(self, path):
        import fileio
        fileio.write_text(path, json.dumps(self.to_json(), separators=(",", ":")))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.from_json(json.load(f))

    # ------------------------------------------------------------------------------------------------ blocks of values (charts, import)
    def parse_range(self, text, default_sheet=None):
        """'Sheet1!A2:B9' (or 'A2:B9') -> (sheet name, r1, c1, r2, c2); None when it is not a range."""
        try:
            toks = E.tokenize(text.strip())
        except E.FormulaError:
            return None
        if len(toks) != 1 or toks[0][0] != "ref":
            return None
        t = toks[0][4]
        sh = t.sheet or default_sheet or self.sheets[self.active].name
        r1, c1, r2, c2 = t.rect()
        if t.kind in ("col", "row"):
            mr, mc = self.extent(sh)
            r2, c2 = min(r2, max(mr, r1)), min(c2, max(mc, c1))
        return sh, r1, c1, r2, c2

    def range_values(self, text, default_sheet=None):
        """The values of a range as a flat list (a column or a row; a block is read row by row)."""
        p = self.parse_range(text, default_sheet)
        if p is None:
            return None
        sh, r1, c1, r2, c2 = p
        return [self.value(sh, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]


def _moved(raw, src_sheet, dst_sheet):
    """A formula that is moved (cut and paste): its references keep pointing at the same cells, so it is not shifted."""
    if src_sheet != dst_sheet:
        return E.qualify(raw, src_sheet)
    return raw


def _new_id(charts):
    ids = {c.get("id") for c in charts}
    i = 1
    while f"chart{i}" in ids:
        i += 1
    return f"chart{i}"


def _chart_refs(ch):
    """The range texts of a chart definition: (getter, setter) pairs."""
    out = []
    if ch.get("x"):
        out.append(("x", None))
    for i, s in enumerate(ch.get("series", [])):
        out.append(("y", i))
    return out


def _map_chart_refs(ch, fn):
    if ch.get("x"):
        ch["x"] = fn(ch["x"])
    for s in ch.get("series", []):
        if s.get("y"):
            s["y"] = fn(s["y"])
        if s.get("name_ref"):
            s["name_ref"] = fn(s["name_ref"])


def _adjust_ref(text, formula_sheet, target_sheet, axis, at, n):
    return E.adjust_formula("=" + text, formula_sheet, target_sheet, axis, at, n)[1:]


def _chart_uses(ch, sheet):
    refs = [ch.get("x")] + [s.get("y") for s in ch.get("series", [])]
    for t in refs:
        if not t:
            continue
        try:
            toks = E.tokenize(t)
        except E.FormulaError:
            continue
        if len(toks) == 1 and toks[0][0] == "ref" and toks[0][4].sheet == sheet:
            return True
    return False
