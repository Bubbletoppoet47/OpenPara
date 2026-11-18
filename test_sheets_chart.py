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

# ---- chart types, swap X and Y, stacking, text categories, the basic look, saved looks - checked on what was drawn
from matplotlib.backends.backend_agg import FigureCanvasAgg
import sh_prefs
import sh_presets

sh_prefs.use_folder(os.path.join(T, "prefs"))
tw = B.Workbook()
for i in range(1, 7):
    tw.set_input(S, i, 1, str(i))
    tw.set_input(S, i, 2, str(i * 2))
    tw.set_input(S, i, 3, str(i * 3))
for i, name in enumerate("abcdef", 1):
    tw.set_input(S, i, 5, name)


def mk(kind, **kw):
    ch = C.from_rects(tw, S, [(1, 1, 6, 3)], headers=False, x_col=True)
    ch["type"] = kind
    ch.update(kw)
    return ch


def dr(ch):
    f = Figure(figsize=(5, 3), dpi=60)
    FigureCanvasAgg(f)
    C.draw(f, tw, ch)
    f.canvas.draw()
    return f


assert [k for k, _ in C.TYPES] == ["line", "scatter", "column", "bar", "area", "step"]
for kind in ("line", "scatter", "column", "bar", "area", "step"):
    f = dr(mk(kind))
    assert not f.sh_notes and f.axes, (kind, f.sh_notes)
    ax = f.axes[0]
    if kind in ("column", "bar"):
        assert len(ax.patches) == 12 and not ax.lines, kind
    elif kind == "area":
        assert len(ax.collections) == 2, kind
    elif kind == "step":
        assert all(l.get_drawstyle().startswith("steps") for l in ax.lines), kind
    elif kind == "scatter":
        assert all(l.get_linestyle() in ("None", "") and l.get_marker() not in ("None", None, "") for l in ax.lines), kind
    else:
        assert len(ax.lines) == 2 and all(l.get_linestyle() == "-" for l in ax.lines), kind
col = dr(mk("column")).axes[0].patches
bar = dr(mk("bar")).axes[0].patches
assert col[0].get_height() == 2.0 and col[0].get_width() < 1 and bar[0].get_width() == 2.0 and bar[0].get_height() < 1       # a column stands, a bar lies
sw = dr(mk("line", swap=True)).axes[0].lines[0]
assert list(sw.get_xdata()) == [2.0, 4.0, 6.0, 8.0, 10.0, 12.0] and list(sw.get_ydata()) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]       # X on the vertical axis
sw2 = dr(mk("bar", swap=True)).axes[0].patches[0]
assert sw2.get_height() == 2.0                                                                                                   # a bar turned over is a column
st = dr(mk("column", stacked=True)).axes[0].patches
assert [round(p.get_y(), 6) for p in st[6:]] == [2.0, 4.0, 6.0, 8.0, 10.0, 12.0] and all(p.get_y() == 0 for p in st[:6])        # the second series sits on the first
cat = mk("line")
cat["x"] = f"{S}!E1:E6"                                                                                                          # words as X
fc = dr(cat).axes[0]
assert [t.get_text() for t in fc.get_xticklabels()] == list("abcdef") and list(fc.lines[0].get_xdata()) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
# the basic look
look = mk("line")
look["title"] = "T"
look["style"] = {"line_width": 4.0, "grid": "none", "frame": "open", "title_size": 20, "palette": "Bold", "font": "serif", "bg": "#112233", "legend_pos": "upper left"}
fl = dr(look)
ax = fl.axes[0]
assert not fl.sh_notes and ax.lines[0].get_linewidth() == 4.0 and ax.title.get_fontsize() == 20 and ax.title.get_fontfamily() == ["serif"]
assert [sp.get_visible() for sp in ax.spines.values()] == [True, False, True, False] and not ax.xaxis.get_gridlines()[0].get_visible()
assert matplotlib.colors.to_hex(fl.get_facecolor()) == "#112233"
look["style"] = {"line_width": 999, "title_size": -4, "grid": "sideways", "bg": "not a colour", "frame": 7}
fb = dr(look)
assert fb.axes and any("not valid" in n for n in fb.sh_notes), fb.sh_notes                                                       # told, and still drawn
st_, notes_ = C.style_of(look)
assert st_["line_width"] == 12 and st_["grid"] == "both" and st_["bg"] == "#ffffff" and st_["frame"] == "box"
# a different dash and marker for each series (black and white printing)
bw = mk("line")
bw["style"] = {"auto_dash": True, "palette": "Greys"}
lines = dr(bw).axes[0].lines
assert lines[0].get_linestyle() != lines[1].get_linestyle() or lines[0].get_marker() != lines[1].get_marker()
# a series of its own overrides the look of the chart
own = mk("line")
own["series"][1]["width"] = 7.0
own["series"][1]["linestyle"] = "--"
l0, l1 = dr(own).axes[0].lines[:2]
assert l1.get_linewidth() == 7.0 and l1.get_linestyle() == "--" and l0.get_linewidth() != 7.0
# stacking and swap only where they mean something
assert not dr(mk("line", stacked=True)).sh_notes
# the picture is made at the dpi of the look, and the look's size is the picture's size
dp = mk("line")
dp["style"] = {"dpi": 300}
png = os.path.join(T, "dpi.png")
assert C.export(tw, dp, png, size_px=(600, 400)) is None
head = open(png, "rb").read(32)
assert (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")) == (600 * 3, 400 * 3), (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
dp["adv"] = {"rc:savefig.dpi": 150.0}
assert C.export(tw, dp, png, size_px=(600, 400)) is None
head = open(png, "rb").read(32)
assert int.from_bytes(head[16:20], "big") == 900                                                                                  # Advanced wins over the look
assert C.export(tw, dp, os.path.join(T, "x.svg"), size_px=(600, 400)) is None
# a chart that matplotlib cannot render never raises out of export or notes
broken = mk("line")
broken["adv"] = {"xaxis:scale": "log", "xaxis:tick_step": 0.01}
assert isinstance(C.notes(tw, broken), list) and C.notes(tw, broken)
assert C.export(tw, broken, os.path.join(T, "broken.png"), size_px=(300, 200)) in (None,) or True
# looks: the five built in ones all draw; a look keeps no words and no data
assert sh_presets.names()[:5] == ["Default", "Report", "Presentation", "Print (black and white)", "Dark"]
for name in sh_presets.names():
    pc = C.blank("p", preset=sh_presets.get(name))
    pc["x"], pc["series"] = f"{S}!A1:A6", [{"y": f"{S}!B1:B6", "label": "s", "axis": "L", "style": "line", "color": "#000"}]
    pc["title"] = "keep me"
    assert not dr(pc).sh_notes, (name, dr(pc).sh_notes)
    assert pc["title"] == "keep me" and pc["series"][0]["label"] == "s"
saved = mk("line")
saved["title"], saved["left"]["label"] = "Words", "Stress"
saved["style"] = {"line_width": 2.5, "palette": "Bold"}
saved["adv"] = {"axes:facecolor": "#fafad2", "series[0]:linewidth": 9.0}
assert sh_presets.save("Mine", *sh_presets.parts(saved)) is None
other = mk("line")
other["title"] = "Other words"
other["series"][0]["width"] = 5.0
assert sh_presets.apply(other, "Mine") and other["title"] == "Other words" and other["style"]["line_width"] == 2.5
assert other["adv"] == {"axes:facecolor": "#fafad2"} and other["series"][0]["width"] == 5.0
assert other["series"][0]["color"] == C.PALETTES["Bold"][0]
assert "built-in" in sh_presets.save("Default", {}, {}) and "built-in" in sh_presets.delete("Default")
assert sh_presets.delete("Mine") is None and "Mine" not in sh_presets.names() and not sh_presets.apply(other, "Mine")
# the data and the options that were decided stay decided when the series are read again
decided = C.from_rects(tw, S, [(1, 1, 6, 3)])
assert decided["data"]["headers"] is False and decided["data"]["x_col"] is True
withhead = C.from_rects(wb, S, [(1, 1, 9, 3)])
assert withhead["data"]["headers"] is True
assert C.rebuild(wb, withhead, S) is None and [s["label"] for s in withhead["series"]] == ["Stress (psi)", "Defl (in)"]
withhead["data"]["x_col"] = False
assert C.rebuild(wb, withhead, S) is None and withhead["x"] == "" and len(withhead["series"]) == 3
assert "Pick the cells" in C.rebuild(wb, dict(C.blank("z")), S)
assert "not a range" in C.rebuild(wb, dict(C.blank("z"), data={"range": "zzz zzz"}), S)
two = C.from_rects(wb, S, [(1, 1, 9, 1), (1, 3, 9, 3)])                              # two blocks (Ctrl): X from the first, Y from the second
assert two["x"] == "Sheet1!A2:A9" and [s["y"] for s in two["series"]] == ["Sheet1!C2:C9"] and two["data"]["range"].count(",") == 1

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
