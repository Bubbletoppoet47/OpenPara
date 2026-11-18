"""Sheets (dev_addons/sheets): the workbook - recalculation, circular references, several sheets, renaming/deleting sheets, insert/delete rows and columns,
copy/fill/paste (relative and $ references), names, undo/redo, the .opsheet file."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import sh_book as B
import sh_engine as E

S = "Sheet1"
T = tempfile.mkdtemp(prefix="opara_sb_")


def vals(wb, sheet, col, rows):
    return [wb.value(sheet, r, col) for r in rows]


# ---- recalculation follows the dependencies, in any order of entry
wb = B.Workbook()
wb.set_input(S, 3, 1, "=A2+A1")
wb.set_input(S, 2, 1, "=A1*3")
wb.set_input(S, 1, 1, "2")
assert vals(wb, S, 1, (1, 2, 3)) == [2.0, 6.0, 8.0]
wb.set_input(S, 1, 1, "10")
assert vals(wb, S, 1, (1, 2, 3)) == [10.0, 30.0, 40.0]
wb.set_input(S, 1, 1, "")
assert vals(wb, S, 1, (2, 3)) == [0.0, 0.0] and wb.cell(S, 1, 1) is None or wb.cell(S, 1, 1).raw is None
wb.set_input(S, 1, 1, "abc")
assert str(wb.value(S, 2, 1)) == "#VALUE!"
wb.set_input(S, 1, 1, "=1/0")
assert str(wb.value(S, 3, 1)) == "#DIV/0!"

# ---- typed text becomes numbers, text, percent, booleans
wb = B.Workbook()
for i, t in enumerate(["12", "-3.5", "1e3", "12%", "text", "TRUE", "'123", " 7 "], 1):
    wb.set_input(S, i, 1, t)
assert vals(wb, S, 1, range(1, 9)) == [12.0, -3.5, 1000.0, 0.12, "text", True, "123", 7.0]
wb.set_input(S, 10, 1, '=A7&"x"')
wb.set_input(S, 11, 1, "=LEN(A7)")
assert wb.value(S, 10, 1) == "123x" and wb.value(S, 11, 1) == 3.0 and wb.display(S, 7, 1) == "123"

# ---- circular references show #CIRC! in both cells and recover when the loop is cut
wb = B.Workbook()
wb.set_input(S, 1, 1, "=A2")
wb.set_input(S, 2, 1, "=A1")
assert str(wb.value(S, 1, 1)) == "#CIRC!" and str(wb.value(S, 2, 1)) == "#CIRC!"
wb.set_input(S, 2, 1, "5")
assert vals(wb, S, 1, (1, 2)) == [5.0, 5.0]
wb.set_input(S, 3, 3, "=C3+1")
assert str(wb.value(S, 3, 3)) == "#CIRC!"

# ---- several sheets: cross-sheet references, renaming rewrites formulas, deleting gives #REF!
wb = B.Workbook()
wb.add_sheet("Data")
wb.set_input("Data", 1, 1, "7")
wb.set_input(S, 1, 3, "=Data!A1*2")
wb.set_input(S, 2, 3, "=SUM(Data!A1:A3)")
assert wb.value(S, 1, 3) == 14.0 and wb.value(S, 2, 3) == 7.0
wb.set_input("Data", 2, 1, "3")
assert wb.value(S, 2, 3) == 10.0
assert wb.rename_sheet("Data", "My Data")
assert wb.cell(S, 1, 3).raw == "='My Data'!A1*2" and wb.value(S, 1, 3) == 14.0
assert not wb.rename_sheet("My Data", "Sheet1") and not wb.rename_sheet("My Data", "a/b") and not wb.rename_sheet("My Data", "x" * 32)
wb.delete_sheet("My Data")
assert wb.cell(S, 1, 3).raw == "=#REF!*2" and str(wb.value(S, 1, 3)) == "#REF!"
assert wb.sheet_names() == [S]
wb.undo()
assert wb.sheet_names() == [S, "My Data"] and wb.value(S, 1, 3) == 14.0
d = wb.duplicate_sheet(S)
assert d.name != S and wb.value(d.name, 1, 3) == 14.0
wb.move_sheet(d.name, 0)
assert wb.sheet_names()[0] == d.name
assert wb.unique_name("Sheet1") not in wb.sheet_names()

# ---- insert / delete rows and columns move the cells and keep the references pointing at the same cells
wb = B.Workbook()
wb.set_input(S, 1, 1, "10")
wb.set_input(S, 2, 1, "=A1*3")
wb.set_input(S, 3, 1, "=A2+A1")
wb.set_input(S, 1, 3, "=SUM(A1:A3)")
wb.insert(S, "r", 1, 1)
assert wb.cell(S, 2, 1).raw == 10.0 and wb.cell(S, 3, 1).raw == "=A2*3" and wb.cell(S, 4, 1).raw == "=A3+A2" and wb.value(S, 4, 1) == 40.0
assert wb.cell(S, 2, 3).raw == "=SUM(A2:A4)" and wb.value(S, 2, 3) == 80.0
wb.undo()
assert wb.cell(S, 2, 1).raw == "=A1*3" and wb.value(S, 3, 1) == 40.0
wb.insert(S, "c", 1, 2)
assert wb.cell(S, 1, 3).raw == 10.0 and wb.cell(S, 2, 3).raw == "=C1*3" and wb.cell(S, 1, 5).raw == "=SUM(C1:C3)"
wb.undo()
wb.delete(S, "r", 2, 1)                                   # row 2 gone: what read it shows #REF!, the range shrinks
assert wb.cell(S, 2, 1).raw == "=#REF!+A1" and str(wb.value(S, 2, 1)) == "#REF!" and wb.cell(S, 1, 3).raw == "=SUM(A1:A2)"
wb.undo()
assert wb.cell(S, 2, 1).raw == "=A1*3"

# ---- copy and paste: relative references move, $ stays; cut keeps the references; paste to another sheet
wb = B.Workbook()
wb.add_sheet("Two")
wb.set_input(S, 1, 1, "2")
wb.set_input(S, 1, 2, "=A1*$A$1+B$5")
wb.set_input(S, 5, 2, "100")
wb.copy_cells(S, (1, 2, 1, 2), S, 2, 3)
assert wb.cell(S, 2, 3).raw == "=B2*$A$1+C$5"
wb.copy_cells(S, (1, 2, 1, 2), "Two", 3, 2)
assert wb.cell("Two", 3, 2).raw == "=A3*$A$1+B$5"
wb.copy_cells(S, (1, 2, 1, 2), S, 8, 2, "values")
assert wb.cell(S, 8, 2).raw == 104.0
wb.set_input(S, 10, 1, "=A1+B5")
wb.copy_cells(S, (10, 1, 10, 1), S, 12, 4, cut=True)
assert wb.cell(S, 12, 4).raw == "=A1+B5" and (wb.cell(S, 10, 1) is None or wb.cell(S, 10, 1).raw is None)
wb.set_input(S, 20, 1, "=B1+1")
wb.paste_to_sheets(S, (20, 1, 20, 1), ["Two"])
assert wb.cell("Two", 20, 1).raw == "=B1+1"                # on the other sheet it reads that sheet's cells

# ---- fill: series and formulas
wb = B.Workbook()
wb.set_input(S, 1, 1, "1")
wb.set_input(S, 2, 1, "2")
wb.fill(S, (1, 1, 2, 1), (3, 1, 6, 1))                     # the target is the part next to the source
assert vals(wb, S, 1, range(1, 7)) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
wb.set_input(S, 1, 2, "=A1*2")
wb.fill(S, (1, 2, 1, 2), (2, 2, 5, 2))
assert wb.cell(S, 5, 2).raw == "=A5*2" and wb.value(S, 5, 2) == 10.0
wb.fill(S, (1, 2, 1, 2), (1, 3, 1, 4))
assert wb.cell(S, 1, 4).raw == "=C1*2"

# ---- names: sheet-scoped first, workbook-wide second; they survive save and load
wb = B.Workbook()
wb.add_sheet("Two")
wb.set_input(S, 1, 1, "10")
assert wb.set_name("NumScrews", "=Sheet1!$A$1", sheet=S)
wb.set_input(S, 3, 1, "=NumScrews*2")
assert wb.value(S, 3, 1) == 20.0
wb.set_input("Two", 1, 1, "=NumScrews")
assert str(wb.value("Two", 1, 1)) == "#NAME?"             # the name belongs to Sheet1 only
assert wb.set_name("Total", "=Sheet1!$A$1")
wb.set_input("Two", 2, 1, "=Total+1")
assert wb.value("Two", 2, 1) == 11.0
wb.set_input(S, 1, 1, "4")
assert wb.value(S, 3, 1) == 8.0 and wb.value("Two", 2, 1) == 5.0
assert not wb.set_name("A1", "=Sheet1!$A$1") and not wb.set_name("1abc", "=Sheet1!$A$1") and not wb.set_name("a b", "=Sheet1!$A$1")
wb.delete_name("Total")
assert str(wb.value("Two", 2, 1)) == "#NAME?"

# ---- styles
wb.set_style(S, (1, 1, 2, 2), bold=True, fmt="0.00")
assert wb.cell(S, 1, 1).st.bold and wb.cell(S, 2, 2).st.fmt == "0.00" and wb.display(S, 1, 1) == "4.00"
wb.set_style(S, (1, 1, 1, 1), italic=True)
assert wb.cell(S, 1, 1).st.bold and wb.cell(S, 1, 1).st.italic

# ---- undo / redo, one step per action; a begin/end group is one step
wb = B.Workbook()
wb.set_input(S, 1, 1, "1")
wb.set_input(S, 1, 1, "2")
wb.undo()
assert wb.value(S, 1, 1) == 1.0
wb.redo()
assert wb.value(S, 1, 1) == 2.0
wb.begin("group")
wb.set_input(S, 2, 1, "5")
wb.set_input(S, 3, 1, "=A2+1")
wb.end()
wb.undo()
assert wb.cell(S, 2, 1) is None or wb.cell(S, 2, 1).raw is None
assert wb.cell(S, 3, 1) is None or wb.cell(S, 3, 1).raw is None
assert wb.can_redo()
wb.redo()
assert wb.value(S, 3, 1) == 6.0
wb.clear(S, (1, 1, 3, 1))
assert all(wb.cell(S, r, 1) is None or wb.cell(S, r, 1).raw is None for r in (1, 2, 3))
wb.undo()
assert wb.value(S, 3, 1) == 6.0

# ---- listeners are told what changed and whether the structure changed
seen = []
wb.listeners.append(lambda changed, structure: seen.append(bool(structure)))
wb.set_input(S, 9, 9, "1")
wb.add_sheet("Late")
assert seen[0] is False and seen[-1] is True

# ---- the .opsheet file: whole workbook, charts, links, widths; the version moves on every change
wb = B.Workbook()
wb.add_sheet("Other")
wb.set_input(S, 1, 1, "3")
wb.set_input(S, 1, 2, "=A1^2+Other!A1")
wb.set_input("Other", 1, 1, "1")
wb.set_style(S, (1, 2, 1, 2), fmt="0.0", bold=True)
wb.get_sheet(S).charts.append({"id": "c1", "title": "t", "series": []})
wb.get_sheet(S).links.append({"kind": "study", "project": "p", "sub": "", "name": "n", "origin": [5, 1], "rows": 2, "cols": 3, "stamp": 1.0})
wb.get_sheet(S).col_w[1] = 90
v0 = wb.version
wb.set_input(S, 5, 5, "9")
assert wb.version != v0
p = os.path.join(T, "w.opsheet")
wb.save(p)
w2 = B.Workbook.load(p)
assert w2.sheet_names() == [S, "Other"] and w2.value(S, 1, 2) == 10.0 and w2.display(S, 1, 2) == "10.0" and w2.cell(S, 1, 2).st.bold
assert w2.get_sheet(S).charts[0]["id"] == "c1" and w2.get_sheet(S).links[0]["origin"] == [5, 1] and w2.get_sheet(S).col_w[1] == 90
open(os.path.join(T, "bad.opsheet"), "w").write("{not json")
try:
    B.Workbook.load(os.path.join(T, "bad.opsheet"))
    raise AssertionError("a broken file must not load")
except (ValueError, OSError):
    pass
open(os.path.join(T, "other.opsheet"), "w").write('{"format": "something-else"}')
try:
    B.Workbook.load(os.path.join(T, "other.opsheet"))
    raise AssertionError("a file of another kind must not load")
except (ValueError, OSError, KeyError):
    pass

# ---- incremental recalculation always equals a full recalculation (random edits, inserts, deletes, undo, with points, ranges and two sheets)
import random
rng = random.Random(20260717)
wb = B.Workbook()
wb.add_sheet("Two")


def same_as_fresh(wb):
    fresh = B.Workbook.from_json(wb.to_json())
    for sh in wb.sheet_names():
        for r in range(1, 16):
            for c in range(1, 9):
                a, b = wb.value(sh, r, c), fresh.value(sh, r, c)
                if str(a) != str(b) and not (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-9 * max(1, abs(b))):
                    return f"{sh} {E.addr(r, c)}: {a!r} vs fresh {b!r}"
    return None


def random_input():
    k = rng.random()
    if k < 0.3:
        return str(rng.randint(-5, 20))
    ref = lambda: E.addr(rng.randint(1, 12), rng.randint(1, 6)) if rng.random() < 0.5 else "Two!" + E.addr(rng.randint(1, 12), rng.randint(1, 6))
    if k < 0.55:
        return f"={ref()}+{ref()}"
    if k < 0.75:
        a, b = rng.randint(1, 8), rng.randint(8, 14)
        c = rng.randint(1, 5)
        return f"=SUM({E.addr(a, c)}:{E.addr(b, c + 1)})"
    if k < 0.9:
        return f"=IF({ref()}>3,{ref()},{ref()}*2)"
    return rng.choice(["", "text", "=1/0", "=AVERAGE(A1:A3)"])


for step in range(400):
    op = rng.random()
    sh = rng.choice([S, "Two"])
    if op < 0.80:
        wb.set_input(sh, rng.randint(1, 12), rng.randint(1, 6), random_input())
    elif op < 0.88:
        wb.insert(sh, rng.choice("rc"), rng.randint(1, 6), 1)
    elif op < 0.94:
        wb.delete(sh, rng.choice("rc"), rng.randint(1, 6), 1)
    elif op < 0.97:
        wb.undo()
    else:
        wb.redo()
    msg = same_as_fresh(wb)
    assert msg is None, f"step {step}: {msg}"

# ---- big blocks stay quick: 20 000 formulas recalculated by one change
import time
wb = B.Workbook()
wb.begin("fill")
wb.set_input(S, 1, 1, "1")
for r in range(2, 20001):
    wb.set_raw(S, r, 1, f"=A{r - 1}+1")
wb.end()
t0 = time.time()
wb.set_input(S, 1, 1, "5")
dt = time.time() - t0
assert wb.value(S, 20000, 1) == 20004.0, wb.value(S, 20000, 1)
assert dt < 2.0, f"recalculating a 20 000 long chain took {dt:.1f} s"

print("OK test_sheets_book")
