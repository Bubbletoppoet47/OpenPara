"""Sheets (dev_addons/sheets): charts - what Insert chart makes from highlighted cells, the numbers a chart reads, several Y series on a left and a right axis,
log axes, limit lines and zones that follow cells, notes, problems named in plain words, PNG / SVG / PDF files, copying."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import sh_book as B
import sh_chart as C
import sh_deps

if sh_deps.matplotlib() is None:
    print("SKIP test_sheets_chart: matplotlib is not installed here")
    raise SystemExit(0)
import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure

S = "Sheet1"
T = tempfile.mkdtemp(prefix="opara_sc_")
wb = B.Workbook()
heads = ["Thickness (in)", "Stress (psi)", "Defl (in)", "Mass (lb)"]
for j, h in enumerate(heads, 1):
    wb.set_input(S, 1, j, h)
for i in range(1, 9):
    wb.set_input(S, i + 1, 1, str(0.04 + 0.01 * i))
    wb.set_input(S, i + 1, 2, f"=20000/A{i + 1}")
    wb.set_input(S, i + 1, 3, f"=0.5/A{i + 1}^2")
    wb.set_input(S, i + 1, 4, f"=A{i + 1}*100")
wb.set_input(S, 12, 1, "allow")
wb.set_input(S, 12, 2, "250000")

# ---- Insert chart from highlighted cells: first column is X, the others Y series, a text header names them
ch = C.from_selection(wb, S, (1, 1, 9, 3))
assert ch["x"] == "Sheet1!A2:A9" and ch["x_label"] == "Thickness (in)" and [s["y"] for s in ch["series"]] == ["Sheet1!B2:B9", "Sheet1!C2:C9"]
assert [s["label"] for s in ch["series"]] == ["Stress (psi)", "Defl (in)"] and all(s["axis"] == "L" for s in ch["series"])
assert len({s["color"] for s in ch["series"]}) == 2 and ch["id"] == "chart1"
one = C.from_selection(wb, S, (2, 2, 9, 2), charts=[ch])                      # one column, no header: against 1, 2, 3 ...
assert one["x"] == "" and one["series"][0]["y"] == "Sheet1!B2:B9" and one["x_label"] == "Point" and one["id"] == "chart2"
row = C.from_selection(wb, S, (2, 1, 2, 4))
assert row["x"] == "" and row["series"][0]["y"] == "Sheet1!A2:D2"
head1 = C.from_selection(wb, S, (1, 2, 9, 2))
assert head1["series"][0]["label"] == "Stress (psi)" and head1["left"]["label"] == "Stress (psi)" and head1["series"][0]["y"] == "Sheet1!B2:B9"

# ---- the numbers: every list as long as the shortest, text and empty cells are gaps
xs, sers = C.data(wb, ch)
assert len(xs) == 8 and abs(xs[0] - 0.05) < 1e-12 and len(sers) == 2 and abs(sers[0][1][0] - 400000.0) < 1e-6
short = C.blank("s")
short["x"], short["series"] = "A2:A9", [{"y": "B2:B4", "axis": "L", "style": "line", "color": "#000"}]
assert len(C.data(wb, short)[0]) == 3
assert C.resolve(wb, 5) == 5.0 and C.resolve(wb, "B12") == 250000.0 and C.resolve(wb, "=B12/2") == 125000.0 and C.resolve(wb, "abc") is None and C.resolve(wb, "") is None
assert C.axis_title("Stress", "psi") == "Stress [psi]" and C.axis_title("Stress", "") == "Stress" and C.axis_title("", "psi") == "[psi]" and C.axis_title("", "") == ""

# ---- drawing: left and right axes, log scales, limit line, zone and note
full = C.blank("full")
full["title"], full["x"], full["x_label"], full["x_units"] = "Study", "A2:A9", "Thickness", "in"
full["series"] = [{"y": "B2:B9", "label": "Stress", "axis": "L", "style": "both", "color": "#2b7de9"},
                  {"y": "C2:C9", "label": "Defl", "axis": "R", "style": "line", "color": "#e8590c"},
                  {"y": "D2:D9", "label": "Mass", "axis": "R", "style": "markers", "color": "#2e7d32"}]
full["left"] = C.axis_def(label="Stress", units="psi", log=True)
full["right"] = C.axis_def(label="Deflection", units="in", min=0, max=1.5)
full["limits"] = [{"axis": "L", "value": "B12", "label": "Allowable", "color": "#c0392b"}, {"axis": "X", "value": 0.08, "label": "Min t", "color": "#555555"}]
full["zones"] = [{"axis": "R", "lo": 0, "hi": 0.2, "label": "OK", "color": "#2e7d32"}]
full["notes"] = [{"x": 0.07, "y": 285714.0, "text": "design point", "axis": "L"}]
fig = Figure(figsize=(6, 4), dpi=100)
C.draw(fig, wb, full)
assert len(fig.axes) == 2                                                          # a second (right) axis only when a series is on it
left, right = fig.axes[0], fig.axes[1]
assert left.get_yscale() == "log" and right.get_yscale() == "linear" and left.get_title() == "Study"
assert left.get_xlabel() == "Thickness [in]" and left.get_ylabel() == "Stress [psi]" and right.get_ylabel() == "Deflection [in]"
assert tuple(right.get_ylim()) == (0.0, 1.5)
assert len(left.lines) >= 3 and len(right.lines) >= 2                                # data + the limit lines
assert len(left.get_legend().get_texts()) == 3                                      # one legend for both axes
assert any(t.get_text() == "design point" for t in left.texts)
fig.canvas.draw()                                                                    # nothing raises when it is really painted
only_left = C.blank("l")
only_left["x"], only_left["series"] = "A2:A9", [{"y": "B2:B9", "label": "", "axis": "L", "style": "line", "color": "#000"}]
f2 = Figure()
C.draw(f2, wb, only_left)
assert len(f2.axes) == 1 and f2.axes[0].get_legend() is None                         # a single unnamed series needs no legend
f3 = Figure()
only_left["x_log"] = True
C.draw(f3, wb, only_left)
assert f3.axes[0].get_xscale() == "log"
f4 = Figure()
C.draw(f4, wb, one)                                                                  # no X range: whole-number ticks
ticks = f4.axes[0].get_xticks()
assert all(abs(t - round(t)) < 1e-9 for t in ticks if 1 <= t <= 8)

# ---- limits and zones follow the cells
wb.set_input(S, 12, 2, "300000")
f5 = Figure()
C.draw(f5, wb, full)
ys = [float(l.get_ydata()[0]) for l in f5.axes[0].lines if len(set(l.get_ydata())) == 1 and len(l.get_ydata()) >= 2]
assert 300000.0 in ys, ys

# ---- bad data never raises; problems say what is wrong in plain words
for broken in (C.blank("empty"), dict(C.blank("b"), x="nowhere", series=[{"y": "B2:B9", "axis": "L", "style": "line", "color": "#000"}]),
               dict(C.blank("t"), series=[{"y": "A12:A12", "axis": "L", "style": "both", "color": "#000"}]),
               dict(C.blank("u"), x="A2:A9", series=[{"y": "B2:B9", "axis": "Q", "style": "weird", "color": "notacolour"}])):
    C.draw(Figure(), wb, broken)
assert C.problems(wb, C.blank("e")) == ["No Y series."]
bad = dict(C.blank("b"), x="A2", series=[{"y": "hello", "axis": "L", "style": "line", "color": "#000"}])
msgs = C.problems(wb, bad)
assert any("hello" in m and "not a range" in m for m in msgs), msgs
assert C.problems(wb, ch) == [] and C.problems(wb, full) == []
text_only = dict(C.blank("t"), series=[{"y": "A12:A12", "axis": "L", "style": "line", "color": "#000"}])
assert C.problems(wb, text_only) == ["The ranges hold no numbers."]

# ---- files: PNG, SVG, PDF
for ext, magic in (("png", b"\x89PNG"), ("svg", b"<?xml"), ("pdf", b"%PDF")):
    p = os.path.join(T, "chart." + ext)
    assert C.export(wb, full, p) is None
    data = open(p, "rb").read()
    assert data[:len(magic)] == magic and len(data) > 1500, ext
png = os.path.join(T, "big.png")
assert C.export(wb, full, png, size_px=(1200, 800), dpi=100) is None
head = open(png, "rb").read(32)
assert int.from_bytes(head[16:20], "big") == 1200 and int.from_bytes(head[20:24], "big") == 800
assert "png, .svg or .pdf" in C.export(wb, full, os.path.join(T, "chart.bmp"))
assert "could not be written" in C.export(wb, full, os.path.join(T, "no_such_folder", "x.png"))

# ---- copying a chart: a new id, moved a little, nothing shared with the original
c2 = C.copy_chart(full, [full])
assert c2["id"] == "chart1" and c2["pos"] == [full["pos"][0] + 24, full["pos"][1] + 24]
c2["series"][0]["label"] = "changed"
c2["limits"][0]["value"] = 1
assert full["series"][0]["label"] == "Stress" and full["limits"][0]["value"] == "B12"

# ---- charts are part of the workbook file and follow renamed sheets
wb.get_sheet(S).charts.append(full)
full["x"], full["series"][0]["y"] = "Sheet1!A2:A9", "Sheet1!B2:B9"
wb.rename_sheet(S, "Study")
assert wb.get_sheet("Study").charts[0]["x"] == "Study!A2:A9" and wb.get_sheet("Study").charts[0]["series"][0]["y"] == "Study!B2:B9"
p = os.path.join(T, "c.opsheet")
wb.save(p)
w2 = B.Workbook.load(p)
assert w2.get_sheet("Study").charts[0]["notes"][0]["text"] == "design point" and w2.get_sheet("Study").charts[0]["right"]["max"] == 1.5

print("OK test_sheets_chart")
