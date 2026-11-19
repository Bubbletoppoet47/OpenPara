"""Sheets: moving cells.  A block that is cut and pasted (or dragged) takes every reference to it along - formulas on every sheet, the moved formulas themselves,
names, the ranges / limits / notes of charts, study blocks - and the move is ONE undo step.  F4 cycles a reference through $B$2, B$2, $B2, B2."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "addons_src", "sheets"), os.path.join(HERE, "shared")]
import sh_book as B, sh_chart as C, sh_engine as E

S = "Sheet1"


def numbers(wb, ch):
    """What the chart shows: its X values and the values of every series (not the references they were read from)."""
    x, sers = C.data(wb, ch)
    return list(x), [list(v) for _s, v in sers]



def raw(wb, sheet, r, c):
    cell = wb.cell(sheet, r, c)
    return None if cell is None else cell.raw


def fresh():
    wb = B.Workbook()
    wb.add_sheet("Two")
    wb.set_input(S, 1, 1, "x"); wb.set_input(S, 1, 2, "y")
    for i in range(1, 5):                                    # A2:B5 = (1, 10) (2, 20) (3, 30) (4, 40)
        wb.set_input(S, i + 1, 1, str(i)); wb.set_input(S, i + 1, 2, str(i * 10))
    return wb


# ---------------------------------------------------------------- engine: move_formula
mv = lambda t, rect, dr, dc, dst=S, sheet=S, src=S: E.move_formula(t, sheet, src, rect, dst, dr, dc)
assert mv("=B2*2+$C$3+SUM(B2:B4)+D9", (2, 2, 4, 3), 3, 1) == "=C5*2+$D$6+SUM(C5:C7)+D9"                 # inside follows (absolute too), outside stays
assert mv("=SUM(B2:B5)", (2, 2, 4, 2), 5, 0) == "=SUM(B2:B5)"                                           # a range that is only partly in the block stays
assert mv("=B2+Two!B2", (2, 2, 4, 3), 0, 5, dst="Two") == "=Two!G2+Two!B2"                              # to another sheet: qualified, other sheets' cells untouched
assert mv("=A:A+3:3", (1, 1, 9, 9), 1, 1) == "=A:A+3:3"                                                  # whole columns / rows stay
assert mv("=B2", (2, 2, 2, 2), -5, 0) == "=#REF!"                                                        # moved off the sheet
assert mv("=A1", (1, 1, 1, 1), 1, 1, sheet="Two") == "=A1"                                               # another sheet's A1 is not this block

# ---------------------------------------------------------------- F4 (engine)
x = "=B2"
seen = []
for _ in range(5):
    x = E.cycle_refs(x, len(x), len(x))[0]
    seen.append(x)
assert seen == ["=$B$2", "=B$2", "=$B2", "=B2", "=$B$2"], seen
assert E.cycle_refs("=SUM(B2,A1:C3)+Sheet1!D4", 6, 6)[0] == "=SUM($B$2,A1:C3)+Sheet1!D4"                 # the reference at the cursor
assert E.cycle_refs("=SUM(B2,A1:C3)+Sheet1!D4", 10, 10)[0] == "=SUM(B2,$A$1:$C$3)+Sheet1!D4"            # a range: both corners together
assert E.cycle_refs("=SUM(B2,A1:C3)+Sheet1!D4", 24, 24)[0] == "=SUM(B2,A1:C3)+Sheet1!$D$4"              # with a sheet name
assert E.cycle_refs("=A1+B2", 1, 6)[0] == "=$A$1+$B$2"                                                  # every reference in the selection
assert E.cycle_refs("=SUM(A:A)", 7, 7)[0] == "=SUM($A:$A)"
assert E.cycle_refs('="A1"+3', 4, 4) is None and E.cycle_refs("hello", 2, 2) is None                    # no reference there: nothing
assert E.cycle_refs("=SUM(A1,B", 7, 7)[0] == "=SUM($A$1,B"                                              # a formula still being typed
assert E.cycle_refs("=A1*2", 2, 2)[0] == "=$A$1*2" and E.cycle_refs("=A1*2", 3, 3)[0] == "=$A$1*2"      # the cursor in or at the end of the reference

# ---------------------------------------------------------------- cut and paste: formulas, names, charts follow
wb = fresh()
wb.set_input(S, 2, 4, "=B2*2")                               # D2
wb.set_input(S, 3, 4, "=SUM(B2:B5)")                         # D3: the whole block B2:B5
wb.set_input(S, 4, 4, "=SUM(A2:B3)")                         # D4: half in the block, half out
wb.set_input(S, 6, 4, "=SUM(B2:B3)")                         # D6: a part of the block, but all of it moves, so it follows
wb.set_input(S, 5, 4, "=$B$4+A4")                            # D5: absolute
wb.set_input("Two", 1, 1, "=Sheet1!B3+1")
wb.set_name("lim", "=Sheet1!$B$4")
wb.set_name("whole", "=Sheet1!B2:B5")
ch = C.from_selection(wb, S, (1, 1, 5, 2), ())
ch["limits"] = [{"axis": "L", "value": "Sheet1!$B$4", "label": "", "color": "#c0392b"}, {"axis": "L", "value": 25.0, "label": "", "color": "#c0392b"}]
ch["zones"] = [{"axis": "L", "lo": "Sheet1!B2", "hi": "Sheet1!B3", "label": "", "color": "#e8590c"}]
ch["notes"] = [{"x": "Sheet1!A3", "y": "Sheet1!B3", "text": "here", "axis": "L"}]
wb.get_sheet(S).charts.append(ch)
before_x, before_y = ch["x"], ch["series"][0]["y"]
assert (before_x, before_y) == ("Sheet1!A2:A5", "Sheet1!B2:B5"), (before_x, before_y)
ys_before = list(C.data(wb, ch)[1][0]) if isinstance(C.data(wb, ch), tuple) else None
d0 = wb.value(S, 3, 4)
n_undo = len(wb._undo)

wb.copy_cells(S, (2, 2, 5, 2), S, 2, 6, cut=True)           # B2:B5 -> F2:F5
assert [raw(wb, S, r, 6) for r in range(2, 6)] == [10.0, 20.0, 30.0, 40.0] and raw(wb, S, 2, 2) is None
assert raw(wb, S, 2, 4) == "=F2*2" and raw(wb, S, 3, 4) == "=SUM(F2:F5)", (raw(wb, S, 2, 4), raw(wb, S, 3, 4))
assert raw(wb, S, 4, 4) == "=SUM(A2:B3)", "a range only partly in the block stays"
assert raw(wb, S, 6, 4) == "=SUM(F2:F3)"
assert raw(wb, S, 5, 4) == "=$F$4+A4"
assert raw(wb, "Two", 1, 1) == "=Sheet1!F3+1"
assert wb.value(S, 3, 4) == d0 and wb.value("Two", 1, 1) == 21.0, (wb.value(S, 3, 4), d0)
assert wb.names["lim"] == "=Sheet1!$F$4" and wb.names["whole"] == "=Sheet1!F2:F5"
assert ch["series"][0]["y"] == "Sheet1!F2:F5" and ch["x"] == "Sheet1!A2:A5", (ch["series"][0]["y"], ch["x"])
assert ch["data"]["range"] == "Sheet1!A1:B5", "the block (B2:B5) does not span the header row of the table: the range is left alone"
assert ch["limits"][0]["value"] == "Sheet1!$F$4" and ch["limits"][1]["value"] == 25.0
assert ch["zones"][0]["lo"] == "Sheet1!F2" and ch["zones"][0]["hi"] == "Sheet1!F3"
assert ch["notes"][0]["x"] == "Sheet1!A3" and ch["notes"][0]["y"] == "Sheet1!F3"
assert len(wb._undo) == n_undo + 1, "the whole move is one undo step"
wb.undo()
assert raw(wb, S, 3, 4) == "=SUM(B2:B5)" and raw(wb, S, 2, 2) == 10.0 and raw(wb, S, 2, 6) is None
assert wb.names["lim"] == "=Sheet1!$B$4" and wb.get_sheet(S).charts[0]["series"][0]["y"] == "Sheet1!B2:B5"
assert wb.get_sheet(S).charts[0]["limits"][0]["value"] == "Sheet1!$B$4"
wb.redo()
assert raw(wb, S, 3, 4) == "=SUM(F2:F5)" and wb.get_sheet(S).charts[0]["series"][0]["y"] == "Sheet1!F2:F5"

# the formulas that move along: a moved cell that pointed into the block moves with it, one that pointed outside keeps pointing there
wb = fresh()
wb.set_input(S, 2, 3, "=B2*2")                               # C2 doubles B2
wb.set_input(S, 3, 3, "=B3+A3")                              # C3: one inside, one outside
wb.copy_cells(S, (2, 2, 3, 3), S, 8, 2, cut=True)           # B2:C3 -> B8:C9
assert raw(wb, S, 8, 3) == "=B8*2" and raw(wb, S, 9, 3) == "=B9+A3", (raw(wb, S, 8, 3), raw(wb, S, 9, 3))
assert wb.value(S, 8, 3) == 20.0 and wb.value(S, 9, 3) == 22.0

# to another sheet
wb = fresh()
wb.set_input(S, 2, 4, "=B2+A2")
wb.copy_cells(S, (2, 2, 3, 2), "Two", 5, 5, cut=True)       # B2:B3 -> Two!E5:E6
assert raw(wb, S, 2, 4) == "=Two!E5+A2" and wb.value(S, 2, 4) == 11.0, raw(wb, S, 2, 4)

# a chart reads the moved data: same numbers
wb = fresh()
ch = C.from_selection(wb, S, (1, 1, 5, 2), ())
wb.get_sheet(S).charts.append(ch)
ref = numbers(wb, ch)
wb.copy_cells(S, (1, 2, 5, 2), S, 1, 7, cut=True)           # the whole Y column B1:B5 -> G1:G5
assert ch["series"][0]["y"] == "Sheet1!G2:G5", ch["series"][0]["y"]
assert numbers(wb, ch) == ref and ref[1] == [[10.0, 20.0, 30.0, 40.0]], "the chart shows the same data after the move"

# inserting a column still adjusts the chart ranges (and now the stored data range and limits)
wb = fresh()
ch = C.from_selection(wb, S, (1, 1, 5, 2), ())
ch["limits"] = [{"axis": "L", "value": "Sheet1!$B$4", "label": "", "color": "#c0392b"}]
wb.get_sheet(S).charts.append(ch)
wb.insert(S, "c", 1)
assert ch["x"] == "Sheet1!B2:B5" and ch["series"][0]["y"] == "Sheet1!C2:C5" and ch["data"]["range"] == "Sheet1!B1:C5" and ch["limits"][0]["value"] == "Sheet1!$C$4", ch

# a study block that moves along keeps its place
wb = fresh()
wb.get_sheet(S).links.append({"kind": "study", "origin": [2, 1], "rows": 3, "cols": 2})
wb.copy_cells(S, (2, 1, 5, 2), S, 10, 4, cut=True)
assert wb.get_sheet(S).links[0]["origin"] == [10, 4]
print("OK sheets move (book)")


# the range a chart was made from is split along the edge of the block, so that reading the chart again (a changed option) finds the same cells
wb = fresh()
ch = C.from_selection(wb, S, (1, 1, 5, 2), ())
wb.get_sheet(S).charts.append(ch)
ref = numbers(wb, ch)
wb.copy_cells(S, (1, 2, 5, 2), S, 1, 7, cut=True)            # the whole Y column B1:B5 -> G1:G5
assert ch["data"]["range"] == "Sheet1!A1:A5, Sheet1!G1:G5", ch["data"]
assert C.rebuild(wb, ch) is None and ch["series"][0]["y"] == "Sheet1!G2:G5" and ch["x"] == "Sheet1!A2:A5", (ch["x"], ch["series"])
assert numbers(wb, ch) == ref
wb2 = fresh()                                                 # a block as wide as the table moves down: split by rows
ch2 = C.from_selection(wb2, S, (1, 1, 5, 2), ())
wb2.get_sheet(S).charts.append(ch2)
wb2.copy_cells(S, (3, 1, 5, 2), S, 13, 1, cut=True)           # A3:B5 -> A13:B15
assert ch2["data"]["range"] == "Sheet1!A1:B2, Sheet1!A13:B15", ch2["data"]["range"]
print("OK sheets move (charts)")
