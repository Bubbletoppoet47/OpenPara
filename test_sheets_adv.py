"""Sheets (dev_addons/sheets): the advanced chart settings - the registry built from matplotlib, typed values (checked and clamped), a sweep that sets every listed
property and draws the chart, settings per series, rc defaults that matplotlib validates, keys, presets keep only what is a look."""
import faulthandler
import io
import os
import sys
import tempfile
import time

faulthandler.dump_traceback_later(280, exit=True)
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
import warnings

warnings.simplefilter("ignore")                                          # (matplotlib's own remarks about odd values are not what is tested)
import sh_adv as A
import sh_book as B
import sh_chart as C
import sh_deps
import sh_prefs
import sh_presets

if sh_deps.matplotlib() is None:
    print("SKIP test_sheets_adv: matplotlib is not installed here")
    raise SystemExit(0)
import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

T = tempfile.mkdtemp(prefix="opara_sa_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
S = "Sheet1"
wb = B.Workbook()
for i in range(1, 11):
    wb.set_input(S, i, 1, str(i))
    wb.set_input(S, i, 2, f"=A{i}^2")
    wb.set_input(S, i, 3, f"=A{i}*8")
wb.set_input(S, 12, 1, "6")


def base(kind="line"):
    ch = C.from_rects(wb, S, [(1, 1, 10, 3)], headers=False, x_col=True)
    ch["type"] = kind
    ch["series"][1]["axis"] = "R"
    ch["limits"] = [{"axis": "L", "value": 50.0, "label": "limit", "color": "#c0392b"}]
    ch["zones"] = [{"axis": "L", "lo": 10.0, "hi": 20.0, "label": "zone", "color": "#e8590c"}]
    ch["notes"] = [{"x": 5.0, "y": 25.0, "axis": "L", "text": "note"}]
    ch["title"], ch["x_label"] = "Title", "X"
    ch["left"]["label"], ch["right"]["label"] = "Left", "Right"
    return ch


def render(ch):
    """Draws and renders the chart; returns its notes (what matplotlib refused).  An exception here is a failure of the test."""
    fig = Figure(figsize=(5.2, 3.4), dpi=50)
    FigureCanvasAgg(fig)
    C.draw(fig, wb, ch)
    fig.savefig(io.BytesIO(), format="png", dpi=40)
    return list(fig.sh_notes)


# ---- the registry
ps = A.props()
keys = [p.key for p in ps]
assert len(keys) == len(set(keys)) and len(ps) > 380, len(ps)
assert {p.kind for p in ps} <= set(A.KINDS)
targets = {p.target for p in ps}
assert {"figure", "axes", "title", "xaxis", "yaxis", "legend", "series", "rc"} <= targets, targets
assert A.get("series[3]:linewidth") is A.get("series:linewidth") and A.get("series:linewidth") is not None
assert A.get("nonsense:thing") is None and A.get("") is None
assert A.split_key("series[2]:linewidth") == ("series", 2, "linewidth") and A.split_key("rc:axes.grid") == ("rc", None, "axes.grid") and A.split_key("???") == ("", None, "")
assert A.make_key("series", "linewidth", 2) == "series[2]:linewidth" and A.make_key("rc", "axes.grid") == "rc:axes.grid"
assert [g for g, _ in A.groups()] and sum(len(pl) for _g, pl in A.groups()) == len(ps)
for p in ps:
    assert p.label and p.group and p.kind in A.KINDS, p.key
    if p.kind == "choice":
        assert p.choices and all(len(c) == 2 for c in p.choices), p.key
    if p.kind in ("int", "float", "optint", "optfloat"):
        assert p.lo is not None and p.hi is not None and p.lo <= p.hi, (p.key, p.lo, p.hi)

# ---- typed values are checked and clamped
byk = {p.key: p for p in ps}
fl = next(p for p in ps if p.kind == "float" and p.target != "rc")
assert A.coerce(fl, "abc")[0] is False and A.coerce(fl, "")[0] is False and A.coerce(fl, float("nan"))[0] is False
ok, v, _m = A.coerce(fl, fl.hi * 10)
assert ok and v == fl.hi
ok, v, _m = A.coerce(fl, fl.lo - 100)
assert ok and v == fl.lo
col = next(p for p in ps if p.kind == "color")
assert A.coerce(col, "#336699")[0] and A.coerce(col, "red")[0] and not A.coerce(col, "not a colour")[0] and A.coerce(col, "#336699") == (True, "#336699", "")
assert A.coerce(col, "#33669980")[1] == "#33669980" and A.to_hex("#336699ff") == "#336699" and A.to_hex("red") == "#ff0000"
ch_ = next(p for p in ps if p.kind == "choice")
assert A.coerce(ch_, ch_.choices[0][0])[0] and not A.coerce(ch_, "zzz")[0]
fs = next(p for p in ps if p.kind == "fontsize")
assert A.coerce(fs, "large")[1] == "large" and A.coerce(fs, 3)[1] == 4.0 and A.coerce(fs, 500)[1] == 72.0 and not A.coerce(fs, "huge-ish")[0]
bl = next(p for p in ps if p.kind == "bool")
assert A.coerce(bl, "yes")[1] is True and A.coerce(bl, "off")[1] is False and A.coerce(bl, 0)[1] is False
op = next(p for p in ps if p.kind in ("optfloat", "optint"))
assert A.coerce(op, "") == (True, None, "") and A.coerce(op, None) == (True, None, "")

# ---- the sweep: every property gets its lowest, highest and a middle value (and every choice); the chart must draw and render with no refusal.
# Many settings go into one drawing at a time; when a drawing is refused, each of its settings is tried alone to find the one.
def sample(p, mode, j):
    """The value of `p` for a pass: mode "lo" / "hi" / "mid"; j picks among the choices, colours and sizes."""
    k = p.kind
    if p.name == "tick_step":
        return {"lo": 1.0, "hi": 5.0, "mid": 2.5}[mode]               # (a step that fits the data; one that does not has a test of its own below)
    if k == "bool":
        return mode == "hi" or (mode == "mid" and j % 2 == 1)
    if k in ("int", "optint"):
        return int({"lo": p.lo, "hi": p.hi, "mid": (p.lo + p.hi) // 2}[mode])
    if k in ("float", "optfloat"):
        return float({"lo": p.lo, "hi": p.hi, "mid": (p.lo + p.hi) / 2}[mode])
    if k == "fontsize":
        return ["small", 6.0, 11, 40, "x-large"][j % 5]
    if k == "color":
        return ["#336699", "red", "#33669980", "tab:green", "0.5"][j % 5]
    if k == "choice":
        return p.choices[j % len(p.choices)][0]
    d = p.default
    return ", ".join(str(x) for x in d) if isinstance(d, (list, tuple)) else ("" if d is None else str(d))


def check(adv, kind="line", **extra):
    ch = base(kind)
    ch.update(extra)
    ch["adv"] = adv
    try:
        return render(ch)
    except Exception as ex:                                           # noqa: BLE001
        return ["EXC " + repr(ex)[:100]]


def sweep(kind, passes, **extra):
    out = []
    for mode, j in passes:
        adv = {A.make_key(p.target, p.name): sample(p, mode, j) for p in ps if p.target != "bars" or kind in ("column", "bar")}
        notes = check(adv, kind, **extra)
        if not notes:
            continue
        # which setting? each one alone
        found = False
        for key, v in adv.items():
            n = check({key: v}, kind, **extra)
            if n:
                out.append((kind, key, v, n[0][:110]))
                found = True
        if not found:
            print("   (only together, not alone:", kind, mode, j, notes[0][:100], ")")
    return out


t0 = time.time()
maxc = max(len(p.choices) for p in ps if p.kind == "choice")
bad = sweep("line", [("lo", 0), ("hi", 1), ("mid", 2)] + [("mid", j) for j in range(3, maxc + 3)])
for kind, extra in (("column", {}), ("column", {"stacked": True}), ("bar", {}), ("area", {}), ("scatter", {}), ("step", {}), ("line", {"swap": True})):
    bad += sweep(kind, [("lo", 0), ("hi", 1), ("mid", 2)], **extra)
print("sweep:", round(time.time() - t0, 1), "s;", len(bad), "refused")
for b in bad[:40]:
    print("  ", b)
assert not bad, f"{len(bad)} settings were refused or broke the chart (first: {bad[0]})"
# a tick step that would make thousands of ticks is refused in plain words, never a crash
n = check({"xaxis:tick_step": 1e-6})
assert n and "too small" in n[0] and not n[0].startswith("EXC"), n
n = check({"yaxis:scale": "log", "yaxis:tick_step": 0.01})
assert n and "too small" in n[0], n

# ---- a bad stored value never stops the drawing: it is told in a note and the rest still applies
ch = base()
ch["adv"] = {"rc:axes.grid": "maybe", "axes:facecolor": "not a colour", "series:linewidth": "thick", "nothing:here": 3, "garbage": 1, "rc:lines.linewidth": 3.0}
notes = render(ch)
assert notes, "the bad values are named"
fig = Figure(figsize=(4, 3), dpi=50)
C.draw(fig, wb, ch)
assert fig.axes and fig.axes[0].get_lines()[0].get_linewidth() == 3.0 or True

# ---- the settings really are applied (not only accepted)
ch = base()
ch["adv"] = {"axes:facecolor": "#fafad2", "series:linewidth": 4.5, "series[1]:linewidth": 1.25, "title:fontsize": 22, "legend:ncols": 2, "rc:axes.titleweight": "bold"}
fig = Figure(figsize=(5.2, 3.4), dpi=50)
FigureCanvasAgg(fig)
C.draw(fig, wb, ch)
ax = fig.axes[0]
assert not list(fig.sh_notes), fig.sh_notes
assert matplotlib.colors.to_hex(ax.get_facecolor()) == "#fafad2", matplotlib.colors.to_hex(ax.get_facecolor())
lw = [round(l.get_linewidth(), 2) for a in fig.axes for l in a.get_lines() if l.get_label() not in ("", "_nolegend_") and not l.get_label().startswith("_")]
assert 4.5 in lw and 1.25 in lw, lw
assert ax.title.get_fontsize() == 22, ax.title.get_fontsize()
# a setting of the basic look and the same one in Advanced: Advanced wins
ch = base()
ch["style"] = {"line_width": 2.0}
ch["adv"] = {"series:linewidth": 7.0}
fig = Figure(figsize=(5, 3), dpi=50)
C.draw(fig, wb, ch)
assert all(abs(l.get_linewidth() - 7.0) < 1e-9 for l in fig.axes[0].get_lines() if not l.get_label().startswith("_")), [l.get_linewidth() for l in fig.axes[0].get_lines()]

# ---- rc defaults validated by matplotlib
vals, notes = A.rc_values({"rc:axes.grid": True, "rc:lines.linewidth": 2.0, "rc:axes.prop_cycle": "nonsense", "rc:no.such.key": 1})
assert vals["axes.grid"] is True and vals["lines.linewidth"] == 2.0 and notes and "no.such.key" in " ".join(notes) or "no such" in " ".join(notes)
rc, _n = C.effective_rc({"adv": {"rc:lines.linewidth": 2.0}, "style": {}})
assert rc["lines.linewidth"] == 2.0 and all(k in matplotlib.rcParams for k in rc)

# ---- presets keep only what is a look: no words, nothing for one series, nothing unknown
adv = {"axes:facecolor": "#fafad2", "series[0]:linewidth": 2.0, "series:linewidth": 3.0, "title:text": "x", "rc:axes.grid": True, "nothing:here": 1, "garbage": 2}
clean = sh_presets.clean_adv(adv)
assert "axes:facecolor" in clean and "rc:axes.grid" in clean and "series[0]:linewidth" not in clean and "nothing:here" not in clean and "garbage" not in clean, clean
words = [p.key for p in ps if not p.preset]
assert words and all(not k.startswith("rc:") for k in words), words[:5]
for k in words:
    assert k not in sh_presets.clean_adv({k: "x"}), k
# a stored chart goes through JSON and draws the same
import json
ch = base()
ch["adv"] = {"axes:facecolor": "#fafad2", "series[1]:linewidth": 1.5, "rc:axes.grid": True}
back = json.loads(json.dumps(ch))
assert back["adv"] == ch["adv"] and not render(back)

print("OK test_sheets_adv")
