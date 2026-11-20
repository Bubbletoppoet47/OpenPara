"""Sheets (dev_addons/sheets): the Import tab - Import CSV.  The reader (separators guessed and chosen, quotes, line breaks inside quotes, BOM, Windows-1252, UTF-16,
decimal commas, rows of different lengths, empty and binary files, limits), what a field becomes (numbers, percentages, booleans, text that starts with =, codes with
leading zeros), the import window, the import at the selected cell and on a new sheet (one undo step each), the question before cells are replaced, the header made bold,
and the Import tab in the ribbon."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication([])
import sh_book as B
import sh_csv as C
import sh_dialogs as D
import sh_engine as E
import sh_prefs
import sh_tab as TAB

T = tempfile.mkdtemp(prefix="opara_sc_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
asked = []
reply = {"q": QMessageBox.StandardButton.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), reply["q"])[1])
answers = {"open": ""}
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (answers["open"], ""))


def write(name, text, encoding="utf-8", raw=None):
    p = os.path.join(T, name)
    with open(p, "wb") as fh:
        fh.write(raw if raw is not None else text.encode(encoding))
    return p


def fresh():
    t = TAB.make_tab()
    t.resize(1300, 800)
    t.show()
    app.processEvents()
    return t


def grid_of(t, r1, c1, r2, c2):
    return [[t.wb.display(t.grid.sheet, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]


# ======================================================================================================== the reader
assert C.guess_delimiter("a,b,c\n1,2,3\n4,5,6\n") == ","
assert C.guess_delimiter("a;b;c\n1;2;3\n") == ";"
assert C.guess_delimiter("a\tb\tc\n1\t2\t3\n") == "\t"
assert C.guess_delimiter("a|b|c\n1|2|3\n") == "|"
assert C.guess_delimiter("one column\nof words\n") == ",", "nothing splits the lines: the default"
assert C.guess_delimiter("a;b;c\n1,5;2,5;3\n4,5;5,5;6\n") == ";", "decimal commas in a semicolon file: the semicolon"
assert C.guess_delimiter('name,note\n"Smith; J","a;b"\n"Jones; K","c;d"\n') == ",", "separators inside quotes do not count"
assert C.guess_delimiter("") == ","

p = C.parse('name,note\n"Smith, J","line one\nline two"\n"say ""hi""",3\n\n\n')
assert p.rows == [["name", "note"], ["Smith, J", "line one\nline two"], ['say "hi"', "3"]] and not p.cut_rows, p.rows
assert C.parse("a,b\r\n1,2\r\n").rows == [["a", "b"], ["1", "2"]], "Windows line ends"
assert C.parse("a,b\n1,2,3,4\n5\n").rows == [["a", "b"], ["1", "2", "3", "4"], ["5"]], "rows are not made the same length"
assert C.parse("a,b\n,\n,\n").rows == [["a", "b"]], "empty lines at the end go"
assert C.parse("a,b\n1,2\n", ";").rows == [["a,b"], ["1,2"]]
big = C.parse("\n".join(f"{i},1" for i in range(10)), max_rows=4)
assert len(big.rows) == 4 and big.cut_rows == 6 and not big.capped, "rows beyond the sheet are counted"
wide = C.parse("1,2,3,4,5\n1,2\n", max_cols=3)
assert wide.rows == [["1", "2", "3"], ["1", "2"]] and wide.cut_cols == 2
cap = C.parse("\n".join("1,2,3" for _ in range(10)), max_cells=12)
assert len(cap.rows) == 4 and cap.cut_rows == 6 and cap.capped, "rows beyond the cell limit are counted too"
try:
    C.parse('a,"b\n1,2\n')                                                  # (an unclosed quote reads to the end: still one field, not an error)
except C.CsvError:
    raise AssertionError("an unclosed quote is read to the end of the file")
try:
    C.parse("a\x00b,c", ",")
except C.CsvError:
    pass

assert C.read_text(b"\xef\xbb\xbfa,b") == ("a,b", "UTF-8"), "a BOM is dropped"
assert C.read_text("Träger,Länge".encode("utf-8")) == ("Träger,Länge", "UTF-8")
assert C.read_text("Träger,Länge".encode("cp1252")) == ("Träger,Länge", "Windows-1252"), "an Excel export from Western Europe"
assert C.read_text("a,b\n1,2".encode("utf-16"))[0] == "a,b\n1,2"
try:
    C.read_text(b"PK\x03\x04\x00\x00\x00binary")
    raise AssertionError("binary data is refused")
except C.CsvError as ex:
    assert "text file" in str(ex)

for name, content, why in (("empty.csv", b"", "empty"), ("blank.csv", b"  \n\n", "empty")):
    try:
        C.load(write(name, "", raw=content))
        raise AssertionError("an empty file is refused")
    except C.CsvError as ex:
        assert why in str(ex), ex
try:
    C.load(os.path.join(T, "nope.csv"))
    raise AssertionError("a missing file is reported")
except C.CsvError as ex:
    assert "could not be read" in str(ex)
assert C.load(write("a.tsv", "a,b\tc\n1,2\t3\n")).delimiter == "\t", ".tsv is tab separated"
assert C.load(write("Loads 1.csv", "a,b\n1,2\n")).name == "Loads 1"

# what a field becomes
assert C.entry("12.5") == (12.5, None) and C.entry("-3") == (-3.0, None) and C.entry("1e3") == (1000.0, None)
assert C.entry("7%") == (0.07, "0%")
assert C.entry("TRUE") == (True, None) and C.entry("false") == (False, None)
assert C.entry("hello") == ("hello", None) and C.entry("2026-11-19") == ("2026-11-19", None), "dates stay text"
assert C.entry("") == (None, None) and C.entry("   ") == (None, None)
assert C.entry("=SUM(A1:A3)") == ("'=SUM(A1:A3)", None), "nothing from a file becomes a formula"
assert C.entry("'quoted") == ("''quoted", None)
assert C.entry("007") == ("'007", None) and C.entry("01234") == ("'01234", None), "codes keep their zeros"
assert C.entry("0") == (0.0, None) and C.entry("0.5") == (0.5, None) and C.entry("10") == (10.0, None)
assert C.entry("1,234.5") == (1234.5, None), "a thousands comma"
assert C.entry("3,14") == ("3,14", None), "without the decimal comma it is text, not a wrong number"
assert C.entry("3,14", True) == (3.14, None) and C.entry("1.234,5", True) == (1234.5, None) and C.entry("-0,5", True) == (-0.5, None)
assert C.entry("12,5%", True) == (0.125, "0%")
assert C.entry("1.5", True) == (1.5, None), "a point is still a point"
assert C.looks_decimal_comma([["a", "3,14"], ["b", "2,5"]]) and not C.looks_decimal_comma([["1.5", "2,5"]]) and not C.looks_decimal_comma([["1,234.5"]])
assert C.looks_like_header([["Case", "Load"], ["A", "12"]]) and not C.looks_like_header([["1", "2"], ["3", "4"]]) and not C.looks_like_header([["a", "b"]])
assert not C.looks_like_header([["a", "b"], ["c", "d"]]), "all words: no way to tell"
assert C.looks_like_header([["Bauteil", "Länge"], ["A", "3,5"]], True) and not C.looks_like_header([["Bauteil", "Länge"], ["A", "3,5"]], False)

# ======================================================================================================== the ribbon
t = fresh()
g, wb = t.grid, t.wb
S = g.sheet
assert [t.ribbon.tabText(i) for i in range(t.ribbon.count())] == ["Home", "Data", "Charts", "Images", "Import", "Engineering", "View"], "the Import tab sits after Images"
assert "csv_in" in t.act and t.act["csv_in"].isEnabled(), "Import CSV is always there"
assert "Import" in t.act["csv_in"].text().replace("\n", " ")
assert "xl_in" in t.act and "study_in" in t.act, "Import study and Import .xlsx stay on the Data tab"

# ======================================================================================================== import at the selected cell
f1 = write("loads.csv", 'Case,Load (kN),Share,Note\nA,12.5,7%,"first, ok"\nB,13,TRUE,"two\nlines"\nC,=1+1,007,\n')
g.select(3, 2)
assert t.csv_import(f1, {"header": True}) == (4, 4)
assert grid_of(t, 3, 2, 6, 5) == [["Case", "Load (kN)", "Share", "Note"], ["A", "12.5", "7%", "first, ok"], ["B", "13", "TRUE", "two\nlines"], ["C", "=1+1", "007", ""]], grid_of(t, 3, 2, 6, 5)
assert wb.get_sheet(S).cells[(3, 2)].st is not None and wb.get_sheet(S).cells[(3, 2)].st.bold, "the header is bold"
assert wb.get_sheet(S).cells[(4, 2)].st is None or not wb.get_sheet(S).cells[(4, 2)].st.bold
assert isinstance(wb.get_sheet(S).cells[(4, 3)].raw, float) and wb.get_sheet(S).cells[(4, 3)].raw == 12.5, "a number is a number"
assert not wb.get_sheet(S).cells[(6, 3)].is_formula, "text that starts with = is not a formula"
assert wb.value(S, 4, 4) == 0.07, "a percentage is its fraction"
assert wb.get_sheet(S).cells[(4, 4)].fmt == "0%"
assert (g.sel() == (3, 2, 6, 5)) and (g.r, g.c) == (3, 2), "the imported block is selected"
assert "Imported loads.csv: 4 row(s), 4 column(s)" in t.status.text(), t.status.text()
assert wb.undo_label() == "Import CSV" and t.is_dirty()
wb.undo()
assert grid_of(t, 3, 2, 6, 5) == [[""] * 4 for _ in range(4)], "one undo takes the whole import away"
wb.redo()
assert wb.display(S, 4, 3) == "12.5"
assert asked == [], "nothing was there: no question"

# the rows go over cells that hold something: asked first
wb.set_input(S, 20, 1, "keep me?")
wb.set_input(S, 21, 2, "42")
g.select(20, 1)
n_ask = len(asked)
reply["q"] = QMessageBox.StandardButton.No
assert t.csv_import(write("small.csv", "x,y\n1,2\n3,4\n"), {}) is None, "No: nothing is imported"
assert len(asked) == n_ask + 1 and "2 cell(s)" in asked[-1], asked[-1]
assert wb.display(S, 20, 1) == "keep me?" and wb.display(S, 21, 2) == "42"
reply["q"] = QMessageBox.StandardButton.Yes
assert t.csv_import(write("small.csv", "x,y\n1,2\n3,4\n"), {}) == (3, 2)
assert grid_of(t, 20, 1, 22, 2) == [["x", "y"], ["1", "2"], ["3", "4"]], "Yes: replaced"
wb.undo()
assert wb.display(S, 20, 1) == "keep me?" and wb.display(S, 21, 2) == "42", "and the cells come back with undo"
# a short row replaces the cells under it too (empty fields empty the cells)
wb.set_input(S, 30, 3, "old")
g.select(30, 1)
t.csv_import(write("ragged.csv", "a,b,c\n1\n"), {"header": False})
assert grid_of(t, 30, 1, 31, 3) == [["a", "b", "c"], ["1", "", ""]]
wb.set_input(S, 40, 1, "x")
g.select(40, 1)
t.csv_import(write("gap.csv", "a,b\n,2\n"), {})
assert grid_of(t, 40, 1, 41, 2) == [["a", "b"], ["", "2"]]

# ======================================================================================================== on a new sheet
f2 = write("Beam data.csv", "x;y\n1,5;2,5\n3,0;4,25\n")
g.select(5, 5)
n_sheets = len(wb.sheets)
assert t.csv_import(f2, {"header": True, "new_sheet": True}) == (3, 2)
assert len(wb.sheets) == n_sheets + 1 and g.sheet == "Beam data", ("named after the file", g.sheet)
assert grid_of(t, 1, 1, 3, 2) == [["x", "y"], ["1.5", "2.5"], ["3", "4.25"]], "semicolon file with decimal commas, guessed"
assert (g.r, g.c) == (1, 1)
assert wb.undo_label() == "Import CSV"
wb.undo()
assert len(wb.sheets) == n_sheets, "ONE undo takes the new sheet and its data away"
t.show_sheet(S)
wb.redo()
assert len(wb.sheets) == n_sheets + 1 and wb.display("Beam data", 2, 1) == "1.5"
t.csv_import(f2, {"new_sheet": True})
assert wb.get_sheet("Beam data (2)") is not None, "the same name again: numbered"
for nm in ("Beam data (2)", "Beam data"):
    t.show_sheet(nm)
t.show_sheet(S)

# the file's name makes a good sheet name
weird = write("a[b]:c*d?e.csv", "1,2\n")
t.csv_import(weird, {"new_sheet": True})
assert B.Workbook.valid_sheet_name(g.sheet), g.sheet
long_name = write("x" * 60 + ".csv", "1,2\n")
t.csv_import(long_name, {"new_sheet": True})
assert len(g.sheet) <= 31
t.show_sheet(S)

# ======================================================================================================== the options
g.select(50, 1)
f3 = write("euro.csv", "Bauteil;Länge (m);Last (kN)\nTräger A;3,50;12,5\nTräger B;4,20;14,75\n", "cp1252")
t.csv_import(f3, {})                                                            # everything guessed: Windows-1252, semicolons, decimal commas, header
assert grid_of(t, 50, 1, 52, 3) == [["Bauteil", "Länge (m)", "Last (kN)"], ["Träger A", "3.5", "12.5"], ["Träger B", "4.2", "14.75"]], grid_of(t, 50, 1, 52, 3)
assert wb.get_sheet(S).cells[(50, 1)].st.bold, "a header is guessed from words over numbers"
assert not (wb.get_sheet(S).cells.get((51, 1)) and wb.get_sheet(S).cells[(51, 1)].st and wb.get_sheet(S).cells[(51, 1)].st.bold)
g.select(60, 1)
t.csv_import(f3, {"delimiter": ",", "decimal": False, "header": False})          # the person chose otherwise
assert wb.display(S, 61, 1).startswith("Träger A;3") and wb.display(S, 61, 2) == "50;12" and not wb.get_sheet(S).cells[(60, 1)].st, grid_of(t, 60, 1, 61, 3)
g.select(70, 1)
t.csv_import(write("tabs.tsv", "a\tb\n1\t2\n"), {})
assert grid_of(t, 70, 1, 71, 2) == [["a", "b"], ["1", "2"]]
g.select(75, 1)
t.csv_import(write("bom.csv", "﻿name,v\nx,1\n", "utf-8"), {})
assert wb.display(S, 75, 1) == "name", "a BOM does not end up in the first cell"
g.select(80, 1)
t.csv_import(write("utf16.csv", "a,b\n1,2\n", "utf-16"), {})
assert grid_of(t, 80, 1, 81, 2) == [["a", "b"], ["1", "2"]]

# files that cannot be imported say so and change nothing
before = wb.to_json()
for name, raw, words in (("empty2.csv", b"", "empty"), ("bin.csv", b"PK\x03\x04\x00\x00junk", "text file")):
    p = write(name, "", raw=raw)
    assert t.csv_import(p, {}) is None
    assert words in t.status.text().lower(), t.status.text()
assert t.csv_import(os.path.join(T, "missing.csv"), {}) is None
assert t.csv_import(write("blanklines.csv", ",\n,\n"), {}) is None, "nothing to import"
assert wb.to_json() == before, "nothing was changed"
answers["open"] = ""
assert t.csv_import() is None, "the file dialog was cancelled"

# ======================================================================================================== the window
cf = C.load(f3)
dlg = D.CsvImportDialog(cf, "B7", "euro", t)
assert dlg.delimiter() == ";" and dlg.header.isChecked() and dlg.decimal.isChecked() and dlg.here.isChecked() and not dlg.new_sheet.isChecked()
assert "Windows-1252" in dlg.info.text() and "3 row(s), 3 column(s)" in dlg.info.text(), dlg.info.text()
assert dlg.table.rowCount() == 3 and dlg.table.columnCount() == 3 and dlg.table.item(1, 1).text() == "3.5", "the preview shows the numbers as they will be"
assert dlg.table.horizontalHeaderItem(0).text() == "A"
dlg.decimal.setChecked(False)
assert dlg.table.item(1, 1).text() == "3,50", "without the decimal comma they are text"
dlg.sep.setCurrentIndex(dlg.sep.findData(","))                                  # another separator: split again, the boxes follow
assert dlg.table.columnCount() == 3 and dlg.parsed.rows[0] == ["Bauteil;Länge (m);Last (kN)"]
assert "B7" in dlg.here.text() and "euro" in dlg.new_sheet.text()
dlg.sep.setCurrentIndex(dlg.sep.findData(";"))
dlg.new_sheet.setChecked(True)
choice = dlg.result_choice()
assert choice["delimiter"] == ";" and choice["new_sheet"] and choice["header"] and choice["decimal"] and len(choice["rows"]) == 3, choice
assert dlg.ok_btn.isEnabled()
many = write("many.csv", "\n".join(f"{i},{i * 2}" for i in range(200)))
d2 = D.CsvImportDialog(C.load(many), "A1", "many", t)
assert d2.table.rowCount() == C.PREVIEW_ROWS and "200 row(s)" in d2.info.text(), "the preview is the start of the file"
d3 = D.CsvImportDialog(C.CsvFile(many, "many", "just words\nmore words\n", "UTF-8", ","), "A1", "many", t)
assert "one column" in d3.msg.text().lower(), d3.msg.text()
d4 = D.CsvImportDialog(C.CsvFile(many, "many", "\n\n", "UTF-8", ","), "A1", "many", t)
assert not d4.ok_btn.isEnabled(), "nothing to import: no Import button"

# the whole thing through the windows, as a person would do it
answers["open"] = f3
g.select(90, 1)
orig_exec = D.CsvImportDialog.exec
D.CsvImportDialog.exec = lambda self: (self.header.setChecked(False), 1)[1]
try:
    r = t.csv_import()
finally:
    D.CsvImportDialog.exec = orig_exec
assert r == (3, 3) and wb.display(S, 90, 1) == "Bauteil" and not (wb.get_sheet(S).cells[(90, 1)].st and wb.get_sheet(S).cells[(90, 1)].st.bold), "the window's choices are used"
D.CsvImportDialog.exec = lambda self: 0
try:
    n_cells = len(wb.get_sheet(S).cells)
    assert t.csv_import() is None and len(wb.get_sheet(S).cells) == n_cells, "Cancel in the window: nothing happens"
finally:
    D.CsvImportDialog.exec = orig_exec

# ======================================================================================================== limits and a big file
g.select(1000, 1)
rows = 3000
bigf = write("bigger.csv", "id,a,b\n" + "\n".join(f"{i},{i * 0.5},{i % 7}" for i in range(rows)))
assert t.csv_import(bigf, {"header": True}) == (rows + 1, 3)
assert wb.display(S, 1000 + rows, 1) == str(rows - 1) and wb.display(S, 1000 + rows, 2) == str((rows - 1) * 0.5).rstrip("0").rstrip(".")
wb.undo()
assert wb.display(S, 1000 + rows, 1) == ""
# a file that would run off the bottom of the sheet: what does not fit is left out and said
g.select(E.MAXROW - 1, 1)
r = t.csv_import(write("edge.csv", "1,1\n2,2\n3,3\n4,4\n"), {})
assert r == (2, 2), r
assert wb.display(S, E.MAXROW, 1) == "2" and wb.display(S, E.MAXROW - 1, 1) == "1"
g.select(1, E.MAXCOL - 1)
r = t.csv_import(write("edgec.csv", "1,2,3,4\n"), {})
assert r == (1, 2), r
assert wb.display(S, 1, E.MAXCOL) == "2"

print("test_sheets_csv OK")
