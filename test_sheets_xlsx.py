"""Sheets (dev_addons/sheets): Excel files - a built workbook round-trips (values, formulas, styles, names, widths, errors), standards functions export as
values with the formula in a comment, a recalculation by LibreOffice (when installed) agrees, and Ian's Analysis.xlsx (when present) matches Excel's own
cached values cell for cell."""
import faulthandler
import os
import shutil
import subprocess
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import sh_book as B
import sh_deps
import sh_engine as E
import sh_xlsx
import std_aisi16

op = sh_deps.openpyxl()
if op is None:
    print("SKIP test_sheets_xlsx: openpyxl is not installed here")
    raise SystemExit(0)
std_aisi16.register()
T = tempfile.mkdtemp(prefix="opara_sx_")
S = "Sheet1"


def num_same(a, b):
    return isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool) and abs(a - b) <= 1e-9 * max(1.0, abs(b))


# ---- a workbook made with openpyxl comes in with its values, formulas, styles, widths and names
wx = op.Workbook()
a = wx.active
a.title = "Loads"
a["A1"], a["A2"], a["A3"] = 10, 20.5, 3
a["B1"] = "=SUM(A1:A3)"
a["B2"] = "=IF(B1>30,\"big\",\"small\")"
a["B3"] = "=VLOOKUP(2,D1:E3,2,FALSE)"
a["D1"], a["E1"], a["D2"], a["E2"], a["D3"], a["E3"] = 1, "one", 2, "two", 3, "three"
a["C1"] = "=Calc!B2*$A$1"
a["C2"] = "=1/0"
a["C3"] = "text"
a["A1"].font = op.styles.Font(bold=True, italic=True, color="FF0000")
a["A2"].number_format = "0.00"
a["A3"].fill = op.styles.PatternFill("solid", fgColor="FFF3BF")
a["B1"].alignment = op.styles.Alignment(horizontal="center")
a.column_dimensions["A"].width = 20
a.freeze_panes = "B2"
b = wx.create_sheet("Calc")
b["A1"] = 4
b["B2"] = "=A1^2+NumScrews"
b["B3"] = "=SUMPRODUCT(Loads!A1:A3,Loads!A1:A3)"
b["B4"] = "='Loads'!A1&\" kips\""
wx.defined_names["NumScrews"] = op.workbook.defined_name.DefinedName("NumScrews", attr_text="Loads!$A$3")
src = os.path.join(T, "built.xlsx")
wx.save(src)

wb, notes = sh_xlsx.import_xlsx(src)
assert wb.sheet_names() == ["Loads", "Calc"] and notes == [], notes
assert wb.value("Loads", 1, 2) == 33.5 and wb.value("Loads", 2, 2) == "big" and wb.value("Loads", 3, 2) == "two"
assert wb.value("Calc", 2, 2) == 19.0 and wb.value("Calc", 3, 2) == 10 * 10 + 20.5 * 20.5 + 9 and wb.value("Calc", 4, 2) == "10 kips"
assert wb.value("Loads", 1, 3) == 190.0 and str(wb.value("Loads", 2, 3)) == "#DIV/0!" and wb.value("Loads", 3, 3) == "text"
st = wb.cell("Loads", 1, 1).st
assert st.bold and st.italic and st.fg and st.fg.upper().endswith("FF0000")
assert wb.cell("Loads", 2, 1).fmt == "0.00" and wb.display("Loads", 2, 1) == "20.50"
assert wb.cell("Loads", 3, 1).st.bg and wb.cell("Loads", 3, 1).st.bg.upper().endswith("FFF3BF")
assert wb.cell("Loads", 1, 2).st.align == "center"
assert wb.get_sheet("Loads").col_w[1] > 100 and wb.get_sheet("Loads").freeze == (1, 1)
assert "NumScrews" in wb.names or "NumScrews" in wb.get_sheet("Loads").names

# ---- export and read back: formulas stay formulas, values, styles, names
wb.set_input("Calc", 6, 1, "=AISI16.J4_4_1(0.0747,0.1875,58000)")
wb.set_input("Calc", 7, 1, "'007")
out = os.path.join(T, "out.xlsx")
exp_notes = sh_xlsx.export_xlsx(wb, out)
r = op.load_workbook(out)
assert r.sheetnames == ["Loads", "Calc"]
assert r["Loads"]["B1"].value == "=SUM(A1:A3)" and r["Calc"]["B2"].value == "=A1^2+NumScrews"
assert r["Loads"]["A1"].font.bold and r["Loads"]["A1"].font.italic and r["Loads"]["A2"].number_format == "0.00"
assert abs(r["Calc"]["A6"].value - 690.508125) < 1e-6, r["Calc"]["A6"].value       # a standards function: the value, with the formula in a comment
assert r["Calc"]["A6"].comment is not None and "AISI16.J4_4_1" in r["Calc"]["A6"].comment.text
assert r["Calc"]["A7"].value == "007" and r["Calc"]["A7"].data_type == "s"
assert any("AISI" in n or "standard" in n.lower() or "comment" in n.lower() for n in exp_notes), exp_notes

# ---- the exported file imports again with the same numbers (a full round trip)
wb2, notes2 = sh_xlsx.import_xlsx(out)
for sh in wb.sheet_names():
    for (rr, cc), cell in wb.get_sheet(sh).cells.items():
        if cell.raw is None:
            continue
        x, y = wb.value(sh, rr, cc), wb2.value(sh, rr, cc)
        assert (num_same(y, x) if isinstance(x, float) else str(x) == str(y)), (sh, E.addr(rr, cc), x, y)

# ---- LibreOffice works the exported file out again: its numbers agree with ours
soffice = shutil.which("soffice") or shutil.which("libreoffice")
if soffice:
    conv = os.path.join(T, "lo")
    os.makedirs(conv)
    prof = os.path.join(T, "lo_profile")
    try:
        subprocess.run([soffice, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "xlsx", "--outdir", conv, out],
                       check=True, capture_output=True, timeout=120)
        lo = op.load_workbook(os.path.join(conv, "out.xlsx"), data_only=True)
        n = 0
        for sh in ("Loads", "Calc"):
            for row in lo[sh].iter_rows():
                for c in row:
                    mine = wb.value(sh, c.row, c.column)
                    if c.value is None or (sh, c.row, c.column) == ("Calc", 6, 1):
                        continue
                    n += 1
                    if isinstance(mine, float):
                        assert num_same(mine, c.value), (sh, c.coordinate, mine, c.value)
                    elif str(mine).startswith("#"):
                        assert str(c.value) == str(mine), (sh, c.coordinate, mine, c.value)
                    else:
                        assert str(mine) == str(c.value), (sh, c.coordinate, mine, c.value)
        assert n >= 15, n
    except (subprocess.SubprocessError, OSError) as ex:
        print("LibreOffice check skipped:", ex)
else:
    print("LibreOffice is not installed here: its recalculation check is skipped")

# ---- a file that is not an Excel file, and a missing file, give a plain message
junk = os.path.join(T, "junk.xlsx")
open(junk, "w").write("not a zip")
for bad in (junk, os.path.join(T, "missing.xlsx")):
    try:
        sh_xlsx.import_xlsx(bad)
        raise AssertionError("a bad file must raise XlsxError")
    except sh_xlsx.XlsxError as ex:
        assert str(ex)

# ---- functions Sheets does not have, charts, pictures and merged cells are reported
wy = op.Workbook()
w = wy.active
w.title = "Sheet1"
w["A1"] = 1
w["A2"] = "=SOMEFUNC(A1)"
w.merge_cells("C1:D2")
ch = op.chart.LineChart()
ch.add_data(op.chart.Reference(w, min_col=1, min_row=1, max_row=2))
w.add_chart(ch, "F2")
p3 = os.path.join(T, "notes.xlsx")
wy.save(p3)
wb3, notes3 = sh_xlsx.import_xlsx(p3)
text = " ".join(notes3)
assert "SOMEFUNC" in text and "chart" in text.lower() and "merged" in text.lower(), notes3
assert str(wb3.value("Sheet1", 2, 1)) == "#NAME?"

# ---- Ian's own workbook (only on a computer that has it): every cell equals Excel's own cached result
for cand in (os.environ.get("OPARA_ANALYSIS_XLSX", ""), r"D:\Mare Motel & Loafing Shed Truss Analysis\Analysis.xlsx", "/tmp/xl/Analysis.xlsx"):
    if cand and os.path.isfile(cand):
        wb4, _n = sh_xlsx.import_xlsx(cand)
        cached = op.load_workbook(cand, data_only=True)
        total = bad = 0
        first = []
        for ws in cached.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if c.value is None:
                        continue
                    total += 1
                    got, want = wb4.value(ws.title, c.row, c.column), c.value
                    if isinstance(want, (int, float)) and not isinstance(want, bool):
                        ok = num_same(got, want)
                    elif isinstance(want, str) and want.startswith("#"):
                        ok = str(got) == want
                    else:
                        ok = got == want or str(got) == str(want)
                    if not ok:
                        bad += 1
                        first.append((ws.title, c.coordinate, want, got))
        assert total > 1000 and bad == 0, (total, bad, first[:5])
        print(f"Analysis.xlsx: {total} cells match Excel's own results")
        break
else:
    print("Analysis.xlsx not found here: that comparison is skipped")

print("OK test_sheets_xlsx")
