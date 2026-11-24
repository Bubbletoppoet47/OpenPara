"""
sh_study.py - a finished parametric study (1D, 2D, 3D FEA or CFD) as a block of cells.

    studies(project)                        the studies a project folder holds [{"name", "sub"}]
    table(project, sub)                     (headers, rows) of values, straight from the study's files
    import_study(wb, sheet, project, sub)   puts the table on a sheet and remembers where it came from (a "link" in sheet.links)
    refresh(wb, sheet, link)                reads the study again into the same place

The block is a snapshot: nothing changes in the sheet until Refresh.  Formulas that you write in the columns right next to the block are filled down by
Refresh for every new row (and removed for rows that are gone), using the last row's formulas as the pattern.
"""
import json
import os

import sh_book as B
import sh_engine as E

STUDY_DIR = "study"
INDEX = "index.json"
FILE = "study.json"
FIRST = "Study 1"


class StudyError(Exception):
    pass


def _root(project, sub=""):
    return os.path.join(project, STUDY_DIR, "studies", sub) if sub else os.path.join(project, STUDY_DIR)


def _file(project, sub=""):
    return os.path.join(_root(project, sub), FILE)


def studies(project):
    """[{"name", "sub"}] of a project folder (empty when it holds no study)."""
    out = []
    try:
        with open(os.path.join(project, STUDY_DIR, INDEX), encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict):
            for x in j.get("studies", []):
                if isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("sub", ""), str):
                    out.append({"name": x["name"], "sub": x.get("sub", "")})
    except (OSError, ValueError, TypeError):
        pass
    if not any(x["sub"] == "" for x in out) and os.path.isfile(_file(project)):
        out.insert(0, {"name": FIRST, "sub": ""})
    return [x for x in out if os.path.isfile(_file(project, x["sub"]))]


def _value(v):
    """A table text -> a number when it is one (the study keeps its input values as text)."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    if t == "":
        return None
    n = E.str_to_num(t)
    if n is not None and all(ch in "0123456789+-.eE" for ch in t):
        return float(n)
    return str(v)


def table(project, sub=""):
    """(headers, rows): '#', one column per changed input, 'Status', one column per recorded output - the same columns as the study's own results table,
    with the numbers kept whole (not rounded for display)."""
    try:
        with open(_file(project, sub), encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError) as ex:
        raise StudyError(f"The study could not be read: {ex}")
    if not isinstance(j, dict) or j.get("format") != "openpara-study":
        raise StudyError("This is not a parametric study.")
    meta = j.get("run_meta") or {}
    params = [tuple(x) for x in meta.get("params", [])]
    outs = [tuple(x) for x in meta.get("outputs", [])]
    heads = ["#"] + [lab for _k, lab in params] + ["Status"] + [lab for _k, lab in outs]
    rows = []
    for c in j.get("cases", []):
        st = str(c.get("status", ""))
        if c.get("early_exit"):
            st += " - EARLY EXIT: " + str(c["early_exit"])
        vals = c.get("values", {}) or {}
        res = c.get("outputs", {}) or {}
        rows.append([_value(c.get("label"))] + [_value(vals.get(k)) for k, _ in params] + [st] + [_value(res.get(k)) for k, _ in outs])
    return heads, rows


def stamp(project, sub=""):
    try:
        return os.path.getmtime(_file(project, sub))
    except OSError:
        return 0.0


def title_of(project, sub=""):
    name = os.path.basename(project.rstrip("/\\")) or project
    for x in studies(project):
        if x["sub"] == sub:
            return f"{name} - {x['name']}"
    return name


# ------------------------------------------------------------------------------------------------------------------ the sheet side
def _link_at(sheet_obj, r, c):
    for ln in sheet_obj.links:
        r0, c0 = ln["origin"]
        if r0 <= r <= r0 + ln.get("rows", 0) and c0 <= c < c0 + ln.get("cols", 0):
            return ln
    return None


def link_at(wb, sheet, r, c):
    s = wb.get_sheet(sheet)
    return _link_at(s, r, c) if s else None


def free_origin(wb, sheet):
    """Where a new imported block goes on a sheet: A1 when the sheet is empty, else two rows under the used area."""
    mr, _mc = wb.extent(sheet)
    return (1, 1) if mr == 0 else (mr + 2, 1)


def formula_columns(wb, sheet_obj, link):
    """The columns right of the block that carry formulas: the columns next to it that have a header or a formula in the last data row, up to the first
    column that has neither."""
    r0, c0 = link["origin"]
    last = r0 + link.get("rows", 0)
    out = []
    c = c0 + link.get("cols", 0)
    while c <= E.MAXCOL:
        head = sheet_obj.cells.get((r0, c))
        cell = sheet_obj.cells.get((last, c)) if link.get("rows", 0) > 0 else None
        has_f = cell is not None and cell.is_formula
        if not has_f and (head is None or head.raw is None):
            break
        out.append(c)
        c += 1
    return out


def overwrite_count(wb, sheet, link, new_rows):
    """How many non-empty cells below the block would be covered if the block grows to `new_rows` data rows."""
    s = wb.get_sheet(sheet)
    r0, c0 = link["origin"]
    old = link.get("rows", 0)
    n = 0
    if new_rows > old:
        for r in range(r0 + old + 1, r0 + new_rows + 1):
            for c in range(c0, c0 + link.get("cols", 0)):
                cell = s.cells.get((r, c))
                if cell is not None and cell.raw is not None:
                    n += 1
    return n


def _write(wb, sheet, link, heads, rows, label, stamp_value):
    """Puts the table in its place as ONE undo step (the inserted columns, the cells, the formulas filled down and the link's own numbers)."""
    wb.begin_group(label)
    try:
        return _write_cells(wb, sheet, link, heads, rows, label, stamp_value)
    finally:
        wb.end_group()


def _write_cells(wb, sheet, link, heads, rows, label, stamp_value):
    s = wb.get_sheet(sheet)
    r0, c0 = link["origin"]
    old_n, old_cols = link.get("rows", 0), link.get("cols", 0)
    n, ncols = len(rows), len(heads)
    fcols = formula_columns(wb, s, link) if old_n > 0 else []
    templates = {}
    for c in fcols:
        cell = s.cells.get((r0 + old_n, c))
        if cell is not None and cell.is_formula:
            templates[c] = (r0 + old_n, cell)
    notes = []
    if ncols > old_cols and old_cols > 0 and fcols:
        d = ncols - old_cols
        wb.insert(sheet, "c", c0 + old_cols, d)                          # the formulas next to the block move over, their references follow
        s = wb.get_sheet(sheet)
        fcols = [c + d for c in fcols]
        templates = {c: (r0 + old_n, s.cells[(r0 + old_n, c)]) for c in fcols if (r0 + old_n, c) in s.cells and s.cells[(r0 + old_n, c)].is_formula}
        notes.append(f"{d} column(s) were inserted so the formulas next to the table stay in place.")
    head_style = B.style_of(bold=True)
    wb.begin(label)
    for r in range(r0, r0 + old_n + 1):
        for c in range(c0, c0 + max(old_cols, ncols)):
            if (r, c) in s.cells:
                wb.set_raw(sheet, r, c, None, None)
    for j, h in enumerate(heads):
        wb.set_raw(sheet, r0, c0 + j, h, head_style)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            wb.set_raw(sheet, r0 + 1 + i, c0 + j, v)
    filled = 0
    for c, (tr, tcell) in templates.items():
        for r in range(r0 + old_n + 1, r0 + n + 1):                      # rows that are new: the last row's formula, moved down
            wb.set_raw(sheet, r, c, E.shift_formula(tcell.raw, r - tr, 0), tcell.st)
            filled += 1
        for r in range(r0 + n + 1, r0 + old_n + 1):                      # rows that are gone
            cell = s.cells.get((r, c))
            if cell is not None and cell.is_formula:
                wb.set_raw(sheet, r, c, None, None)
    wb.end()
    link["rows"], link["cols"], link["stamp"] = n, ncols, stamp_value
    if filled:
        notes.append(f"{filled} formula cell(s) were filled down.")
    return notes


def import_study(wb, sheet, project, sub="", origin=None):
    """Puts a study's table on `sheet` (at `origin` = (row, column), else under what is there) and remembers the source.  Returns (link, notes)."""
    heads, rows = table(project, sub)
    s = wb.get_sheet(sheet)
    link = {"kind": "study", "project": project, "sub": sub, "name": title_of(project, sub), "origin": list(origin or free_origin(wb, sheet)),
            "rows": 0, "cols": 0, "stamp": stamp(project, sub)}
    wb.begin_group("Import study")
    try:
        s.links.append(link)
        notes = _write(wb, sheet, link, heads, rows, "Import study", link["stamp"])
    except BaseException:
        if link in s.links:
            s.links.remove(link)
        raise
    finally:
        wb.end_group()
    if not rows:
        notes.append("The study has no results yet: run it, then use Refresh from study.")
    return link, notes


def refresh(wb, sheet, link, force=False):
    """Reads the study again into its block.  Returns (done, notes); done is False when the block would grow over cells that hold something else, unless
    force=True."""
    heads, rows = table(link["project"], link.get("sub", ""))
    if not force and overwrite_count(wb, sheet, link, len(rows)):
        return False, [f"The table has grown and would cover {overwrite_count(wb, sheet, link, len(rows))} cell(s) that hold other things."]
    notes = _write(wb, sheet, link, heads, rows, "Refresh from study", stamp(link["project"], link.get("sub", "")))
    return True, notes


def refresh_all(wb, resolve=None, select=None):
    """Reads every imported study of the workbook again (the Workbench does it when a Sheets block takes new results).  `resolve(link)` gives the folder a link reads from now (a
    link that came from a Workbench block names the block, and its folder changes from one session to the next) or None when the study is no longer there; `select(link)` False
    leaves a link alone.  -> (the blocks read, [what was not done and why])."""
    done, notes = 0, []
    for s in list(wb.sheets):
        for ln in list(s.links):
            name = ln.get("name", "study")
            if select is not None and not select(ln):
                continue
            if resolve is not None:
                path = resolve(ln)
                if path is None:
                    notes.append(f"{name}: its study is no longer wired into the block.")
                    continue
                ln["project"] = path
            try:
                ok, why = refresh(wb, s.name, ln)
            except StudyError as ex:
                notes.append(f"{name}: {ex}")
                continue
            if ok:
                done += 1
            else:
                notes.append(f"{name}: {why[0]}")
    return done, notes


def is_stale(link):
    """True when the study has been saved again since the block was read."""
    return stamp(link["project"], link.get("sub", "")) > link.get("stamp", 0.0) + 0.5


def block_rect(link):
    """(first row, first column, last row, last column) of the cells of an imported block: the header row and the data under it."""
    r0, c0 = link["origin"]
    return r0, c0, r0 + max(0, link.get("rows", 0)), c0 + max(1, link.get("cols", 1)) - 1


def is_near(wb, sheet_obj, link, r, c):
    """True when (r, c) is in the block, one cell around it, or in the formula columns next to it that Refresh keeps filled."""
    r1, c1, r2, c2 = block_rect(link)
    try:
        fc = formula_columns(wb, sheet_obj, link)
    except Exception:                                                   # noqa: BLE001 - only a hint
        fc = []
    c2 = max([c2] + [x for x in fc if isinstance(x, int)])
    return r1 - 1 <= r <= r2 + 1 and c1 - 1 <= c <= c2 + 1


def remove_link(wb, sheet, link, clear=False):
    """Takes the block off the sheet's imported studies, so Refresh from study no longer fills it.  clear=True also empties the cells of the block (values and
    looks; formulas next to it stay).  One undo step."""
    s = wb.get_sheet(sheet)
    if link not in s.links:
        return False
    rect = block_rect(link)
    wb.begin_group("Delete study")
    try:
        s.links.remove(link)
        if clear:
            wb.clear(sheet, rect, styles=True)
    finally:
        wb.end_group()
    wb._structure()
    return True
