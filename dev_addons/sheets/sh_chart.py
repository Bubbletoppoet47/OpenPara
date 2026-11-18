"""
sh_chart.py - charts of Sheets, drawn with matplotlib (it comes with the Playground).  No window in it: sh_dialogs.py edits a chart, sh_grid.py shows it.

A chart is a dictionary kept in the sheet (sheet.charts), so it is saved with the file:

    {"id": "chart1", "title": "",
     "x": "Sheet1!A2:A20",  "x_label": "", "x_units": "", "x_log": False, "x_min": None, "x_max": None,     one independent range
     "left":  {"label": "", "units": "", "log": False, "min": None, "max": None},                             the two vertical axes
     "right": {...},
     "series": [{"y": "Sheet1!B2:B20", "label": "", "axis": "L" | "R", "style": "line" | "markers" | "both", "color": "#2b7de9"}],
     "limits": [{"axis": "L" | "R" | "X", "value": 12.0 or "Sheet1!$B$2", "label": "", "color": "#c0392b"}],  a line at a value
     "zones":  [{"axis": "L" | "R" | "X", "lo": ..., "hi": ..., "label": "", "color": "#e8590c"}],            a shaded band
     "notes":  [{"x": ..., "y": ..., "text": "", "axis": "L" | "R"}],                                          text with an arrow
     "grid": True, "legend": True, "pos": [x, y], "size": [w, h]}

Several series share the one X range (each on the left or the right Y axis).  A limit, zone or note value is a number or a cell reference, so it
moves with the sheet.
"""
import copy
import math

import sh_deps
import sh_engine as E

PALETTE = ["#2b7de9", "#e8590c", "#0e7f86", "#7c4dcc", "#2e7d32", "#c2255c", "#8a6d00", "#5f6b7a"]
STYLES = ("line", "markers", "both")
FILE_TYPES = {"png": "PNG image (*.png)", "svg": "SVG drawing (*.svg)", "pdf": "PDF file (*.pdf)"}
DEFAULT_SIZE = (520, 340)


def new_id(charts):
    ids = {c.get("id") for c in charts}
    i = 1
    while f"chart{i}" in ids:
        i += 1
    return f"chart{i}"


def axis_def(**kw):
    d = {"label": "", "units": "", "log": False, "min": None, "max": None}
    d.update(kw)
    return d


def blank(chart_id, title=""):
    return {"id": chart_id, "title": title, "x": "", "x_label": "", "x_units": "", "x_log": False, "x_min": None, "x_max": None,
            "left": axis_def(), "right": axis_def(), "series": [], "limits": [], "zones": [], "notes": [], "grid": True, "legend": True,
            "pos": [40, 40], "size": list(DEFAULT_SIZE)}


def _qualified(sheet, r1, c1, r2, c2):
    return f"{E.quote_sheet(sheet)}!{E.addr(r1, c1)}:{E.addr(r2, c2)}"


def from_selection(wb, sheet, rect, charts=()):
    """The chart that Insert chart makes from a highlighted block, the way Excel does for a scatter: the first column is X, every other column is one
    Y series, and a text cell at the top of a column is that series' name.  One column alone is plotted against 1, 2, 3 ...  A block of one row is
    read the same way turned sideways."""
    r1, c1, r2, c2 = rect
    ch = blank(new_id(charts))
    rows, cols = r2 - r1 + 1, c2 - c1 + 1
    if rows == 1 and cols > 1:                                    # one row of numbers: one series, plotted against 1, 2, 3 ...
        ch["series"].append({"y": _qualified(sheet, r1, c1, r1, c2), "label": "", "axis": "L", "style": "both", "color": PALETTE[0]})
        ch["x_label"] = "Point"
        return ch
    header = False
    probe = [wb.value(sheet, r1, c) for c in range(c1, c2 + 1)]
    if all(isinstance(v, str) for v in probe if v is not None) and any(isinstance(v, str) for v in probe) and rows > 1:
        header = True
    top = r1 + 1 if header else r1
    names = [str(v) if isinstance(v, str) else "" for v in probe] if header else [""] * cols
    if cols == 1:
        ch["series"].append({"y": _qualified(sheet, top, c1, r2, c1), "label": names[0], "axis": "L", "style": "line", "color": PALETTE[0]})
        ch["x_label"] = "Point"
    else:
        ch["x"] = _qualified(sheet, top, c1, r2, c1)
        ch["x_label"] = names[0]
        for i in range(1, cols):
            ch["series"].append({"y": _qualified(sheet, top, c1 + i, r2, c1 + i), "label": names[i], "axis": "L", "style": "both" if r2 - top < 40 else "line",
                                 "color": PALETTE[(i - 1) % len(PALETTE)]})
    if len(ch["series"]) == 1 and ch["series"][0]["label"]:
        ch["left"]["label"] = ch["series"][0]["label"]
    return ch


# ------------------------------------------------------------------------------------------------------------------ reading the data
def _nums(wb, text):
    """The numbers of a range as a list (None where the cell is empty, text or an error)."""
    vals = wb.range_values(text) if text else None
    if vals is None:
        return None
    out = []
    for v in vals:
        out.append(float(v) if isinstance(v, float) and v == v and not math.isinf(v) else (float(v) if isinstance(v, int) and not isinstance(v, bool) else None))
    return out


def resolve(wb, v, sheet=None):
    """A guide value: a number as it is, a cell reference or a formula worked out now; None when it is not a number."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    t = str(v).strip()
    try:
        return float(t)
    except ValueError:
        pass
    r = wb.evaluate(t if t.startswith("=") else "=" + t, sheet)
    return float(r) if isinstance(r, float) and r == r else None


def data(wb, ch):
    """(xs, [(series, ys)]) - the numbers of the chart, every list as long as the shortest range.  xs is 1, 2, 3 ... when the chart has no X range."""
    sers = []
    for s in ch.get("series", []):
        ys = _nums(wb, s.get("y", ""))
        sers.append((s, ys if ys is not None else []))
    n = min([len(ys) for _s, ys in sers] or [0])
    xs = _nums(wb, ch.get("x", "")) if ch.get("x") else None
    if xs is not None:
        n = min(n, len(xs)) if sers else len(xs)
    xs = xs[:n] if xs is not None else [float(i + 1) for i in range(n)]
    return xs, [(s, ys[:n]) for s, ys in sers]


def problems(wb, ch):
    """Short plain notes about what is wrong with the chart's ranges (empty list when it is fine)."""
    out = []
    if not ch.get("series"):
        out.append("No Y series.")
    if ch.get("x") and wb.parse_range(ch["x"]) is None:
        out.append(f"The X range {ch['x']} is not a range.")
    for i, s in enumerate(ch.get("series", [])):
        if wb.parse_range(s.get("y", "")) is None:
            out.append(f"Series {i + 1}: {s.get('y') or 'no range'} is not a range.")
    if not out:
        xs, sers = data(wb, ch)
        if not xs or not any(y is not None for _s, ys in sers for y in ys):
            out.append("The ranges hold no numbers.")
    return out


def axis_title(label, units):
    label, units = (label or "").strip(), (units or "").strip()
    return f"{label} [{units}]" if label and units else (label or (f"[{units}]" if units else ""))


# ------------------------------------------------------------------------------------------------------------------ drawing
INK, MUTED, GRID = "#1f2a3c", "#6a7790", "#e3e8f0"


def _color(value, fallback):
    """The colour as matplotlib takes it, or `fallback` when the file holds something that is not a colour."""
    try:
        from matplotlib.colors import is_color_like
        return value if value and is_color_like(value) else fallback
    except Exception:                                          # noqa: BLE001
        return fallback


def draw(fig, wb, ch, compact=False):
    """Draws the chart onto a matplotlib Figure (it is cleared first).  Never raises for bad data: it draws what it can."""
    fig.clear()
    fig.patch.set_facecolor("white")
    ax = fig.add_subplot(111)
    ax2 = None
    xs, sers = data(wb, ch)
    fs = 8 if compact else 9
    right_used = any(s.get("axis") == "R" for s, _ys in sers) or any(g.get("axis") == "R" for k in ("limits", "zones", "notes") for g in ch.get(k, []))
    if right_used:
        ax2 = ax.twinx()
    axes = {"L": ax, "R": ax2 or ax}
    handles = []
    for i, (s, ys) in enumerate(sers):
        a = axes["R" if s.get("axis") == "R" else "L"]
        color = _color(s.get("color"), PALETTE[i % len(PALETTE)])
        style = s.get("style", "line")
        label = s.get("label") or f"Series {i + 1}"
        line, = a.plot([x if x is not None else math.nan for x in xs], [y if y is not None else math.nan for y in ys], color=color, linewidth=1.6,
                       linestyle="-" if style in ("line", "both") else "None", marker="o" if style in ("markers", "both") else None, markersize=4, label=label)
        handles.append(line)

    for g in ch.get("zones", []):
        lo, hi = resolve(wb, g.get("lo")), resolve(wb, g.get("hi"))
        if lo is None or hi is None:
            continue
        lo, hi = min(lo, hi), max(lo, hi)
        color = _color(g.get("color"), "#e8590c")
        if g.get("axis") == "X":
            ax.axvspan(lo, hi, color=color, alpha=0.14, linewidth=0)
            if g.get("label"):
                ax.text((lo + hi) / 2, 0.98, g["label"], transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=fs - 1, color=color)
        else:
            a = axes["R" if g.get("axis") == "R" else "L"]
            a.axhspan(lo, hi, color=color, alpha=0.14, linewidth=0)
            if g.get("label"):
                a.text(0.015, (lo + hi) / 2, g["label"], transform=a.get_yaxis_transform(), ha="left", va="center", fontsize=fs - 1, color=color)
    for g in ch.get("limits", []):
        v = resolve(wb, g.get("value"))
        if v is None:
            continue
        color = _color(g.get("color"), "#c0392b")
        if g.get("axis") == "X":
            ax.axvline(v, color=color, linestyle="--", linewidth=1.2)
            if g.get("label"):
                ax.text(v, 0.02, " " + g["label"], transform=ax.get_xaxis_transform(), ha="left", va="bottom", fontsize=fs - 1, color=color)
        else:
            a = axes["R" if g.get("axis") == "R" else "L"]
            a.axhline(v, color=color, linestyle="--", linewidth=1.2)
            if g.get("label"):
                a.text(0.99, v, g["label"] + " ", transform=a.get_yaxis_transform(), ha="right", va="bottom", fontsize=fs - 1, color=color)
    for g in ch.get("notes", []):
        x, y = resolve(wb, g.get("x")), resolve(wb, g.get("y"))
        if x is None or y is None or not g.get("text"):
            continue
        a = axes["R" if g.get("axis") == "R" else "L"]
        a.annotate(g["text"], xy=(x, y), xytext=(14, 18), textcoords="offset points", fontsize=fs - 0.5, color=INK,
                   arrowprops={"arrowstyle": "->", "color": MUTED, "linewidth": 0.9},
                   bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "#c8d0de", "lw": 0.8})

    ax.set_xlabel(axis_title(ch.get("x_label"), ch.get("x_units")), fontsize=fs, color=INK)
    ax.set_ylabel(axis_title(ch.get("left", {}).get("label"), ch.get("left", {}).get("units")), fontsize=fs, color=INK)
    if ax2 is not None:
        ax2.set_ylabel(axis_title(ch.get("right", {}).get("label"), ch.get("right", {}).get("units")), fontsize=fs, color=INK)
    if ch.get("x_log"):
        ax.set_xscale("log")
    elif not ch.get("x"):                                      # 1, 2, 3 ... : whole numbers only
        from matplotlib.ticker import MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    if ch.get("left", {}).get("log"):
        ax.set_yscale("log")
    if ax2 is not None and ch.get("right", {}).get("log"):
        ax2.set_yscale("log")
    _limits(ax, "x", ch.get("x_min"), ch.get("x_max"), wb)
    _limits(ax, "y", ch.get("left", {}).get("min"), ch.get("left", {}).get("max"), wb)
    if ax2 is not None:
        _limits(ax2, "y", ch.get("right", {}).get("min"), ch.get("right", {}).get("max"), wb)
    if ch.get("title"):
        ax.set_title(ch["title"], fontsize=fs + 2, color=INK, fontweight="bold", pad=8)
    for a in [ax] + ([ax2] if ax2 is not None else []):
        a.tick_params(labelsize=fs - 1, colors=MUTED)
        for sp in a.spines.values():
            sp.set_color("#c8d0de")
    if ch.get("grid", True):
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    if ch.get("legend", True) and len(handles) > 0 and (len(handles) > 1 or any(s.get("label") for s, _ in sers)):
        ax.legend(handles=handles, fontsize=fs - 1, frameon=True, framealpha=0.92, edgecolor="#c8d0de", loc="best")
    try:
        fig.tight_layout(pad=0.9)
    except (ValueError, RuntimeError):
        pass
    return fig


def _limits(ax, which, lo, hi, wb):
    lo, hi = resolve(wb, lo), resolve(wb, hi)
    if lo is None and hi is None:
        return
    cur = ax.get_xlim() if which == "x" else ax.get_ylim()
    new = (lo if lo is not None else cur[0], hi if hi is not None else cur[1])
    if new[0] == new[1]:
        return
    (ax.set_xlim if which == "x" else ax.set_ylim)(*new)


def figure(wb, ch, size_px=None, dpi=100):
    """A matplotlib Figure with the chart drawn (no pyplot, so nothing keeps it alive); None when matplotlib is missing."""
    if sh_deps.matplotlib() is None:
        return None
    from matplotlib.figure import Figure
    w, h = size_px or ch.get("size") or DEFAULT_SIZE
    fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    draw(fig, wb, ch)
    return fig


def export(wb, ch, path, size_px=(1000, 650), dpi=200):
    """Writes the chart as PNG, SVG or PDF (by the file name's ending).  Returns None, or a plain message when it did not work."""
    ext = str(path).rsplit(".", 1)[-1].lower()
    if ext not in FILE_TYPES:
        return "Choose a file name ending in .png, .svg or .pdf."
    fig = figure(wb, ch, size_px, dpi=100)
    if fig is None:
        return "matplotlib is needed to draw charts."
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig)
        fig.savefig(path, dpi=dpi if ext == "png" else 100, format=ext, facecolor="white")
    except (OSError, ValueError, RuntimeError) as ex:
        return f"The chart could not be written: {ex}"
    return None


def copy_chart(ch, charts):
    c = copy.deepcopy(ch)
    c["id"] = new_id(charts)
    c["pos"] = [ch.get("pos", [40, 40])[0] + 24, ch.get("pos", [40, 40])[1] + 24]
    return c
