"""
sh_chart.py - charts of Sheets, drawn with matplotlib (it comes with the Playground).  No window in it: sh_panel.py edits a chart, sh_grid.py shows it.

A chart is a dictionary kept in the sheet (sheet.charts), so it is saved with the file:

    {"id": "chart1", "title": "", "type": "line" | "scatter" | "column" | "bar" | "area" | "step",  "swap": False,  "stacked": False,
     "data": {"range": "Sheet1!A1:C20", "headers": None, "x_col": None, "switch": False},   where the series came from (None = decided from the cells)
     "x": "Sheet1!A2:A20",  "x_label": "", "x_units": "", "x_log": False, "x_min": None, "x_max": None,     one independent range
     "left":  {"label": "", "units": "", "log": False, "min": None, "max": None},                             the two dependent axes
     "right": {...},
     "series": [{"y": "Sheet1!B2:B20", "label": "", "axis": "L" | "R", "style": "line" | "markers" | "both", "color": "#2b7de9",
                 "width": 1.6, "linestyle": "-", "marker": "o", "marker_size": 4}],              (the last four are optional: the chart's own look when missing)
     "limits": [{"axis": "L" | "R" | "X", "value": 12.0 or "Sheet1!$B$2", "label": "", "color": "#c0392b"}],  a line at a value
     "zones":  [{"axis": "L" | "R" | "X", "lo": ..., "hi": ..., "label": "", "color": "#e8590c"}],            a shaded band
     "notes":  [{"x": ..., "y": ..., "text": "", "axis": "L" | "R"}],                                          text with an arrow
     "style": {...},   the basic look (STYLE_SPEC: fonts, line widths, grid, frame, legend ...); missing keys are the defaults
     "adv": {...},     the advanced options (sh_adv), which win over the basic look
     "grid": True, "legend": True, "pos": [x, y], "size": [w, h]}

Several series share the one X range (each on the left or the right Y axis).  "swap" puts X on the vertical axis.  A limit, zone or note value is a number or a cell
reference, so it moves with the sheet.  draw() never raises for a bad chart: it draws what it can and leaves plain notes in fig.sh_notes.
"""
import copy
import math

import sh_adv
import sh_deps
import sh_engine as E

PALETTE = ["#2b7de9", "#e8590c", "#0e7f86", "#7c4dcc", "#2e7d32", "#c2255c", "#8a6d00", "#5f6b7a"]
PALETTES = {
    "Default": PALETTE,
    "Colour-blind safe": ["#0072b2", "#e69f00", "#009e73", "#d55e00", "#cc79a7", "#56b4e9", "#f0e442", "#000000"],
    "Bold": ["#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf"],
    "Soft": ["#8fb8de", "#f5b97f", "#8fd1c2", "#c3b1e1", "#a8d5a2", "#f2a6c0", "#e3d48a", "#b6bfcc"],
    "Greys": ["#111111", "#555555", "#888888", "#bbbbbb", "#333333", "#777777", "#aaaaaa", "#d0d0d0"],
    "Engineering": ["#1b4f9c", "#c0392b", "#2e7d32", "#8e44ad", "#d68910", "#117a8b", "#6c3483", "#566573"],
}
STYLES = ("line", "markers", "both")
TYPES = [("line", "Line"), ("scatter", "Scatter"), ("column", "Column"), ("bar", "Bar (horizontal)"), ("area", "Area"), ("step", "Step")]
FILE_TYPES = {"png": "PNG image (*.png)", "svg": "SVG drawing (*.svg)", "pdf": "PDF file (*.pdf)"}
DEFAULT_SIZE = (520, 340)
INK, MUTED, GRID, FRAME = "#1f2a3c", "#6a7790", "#e3e8f0", "#c8d0de"
AUTO_DASH = ["-", "--", ":", "-.", "longdash", "dashdotdot"]
AUTO_MARK = ["o", "s", "^", "D", "v", "P"]

# the basic look: key -> (kind, default, low, high, choices).  kind: bool | float | optfloat (None = automatic) | color | choice | text
_LS = [k for k, _ in sh_adv.LINESTYLES]
STYLE_SPEC = {
    "font": ("text", "", None, None, None),
    "title_size": ("optfloat", None, 5, 60, None), "label_size": ("optfloat", None, 5, 60, None), "tick_size": ("optfloat", None, 4, 60, None),
    "legend_size": ("optfloat", None, 4, 60, None),
    "title_bold": ("bool", True, None, None, None), "label_bold": ("bool", False, None, None, None),
    "text_color": ("color", INK, None, None, None), "tick_color": ("color", MUTED, None, None, None),
    "line_width": ("float", 1.6, 0.25, 12, None), "line_style": ("choice", "-", None, None, _LS),
    "marker": ("choice", "o", None, None, [k for k, _ in sh_adv.MARKERS]), "marker_size": ("float", 4.0, 1, 24, None),
    "auto_dash": ("bool", False, None, None, None),
    "palette": ("choice", "", None, None, [""] + list(PALETTES)),
    "bg": ("color", "#ffffff", None, None, None), "plot_bg": ("color", "#ffffff", None, None, None),
    "grid": ("choice", "both", None, None, ["both", "horizontal", "vertical", "none"]), "grid_style": ("choice", "-", None, None, _LS),
    "grid_width": ("float", 0.8, 0.1, 4, None), "grid_color": ("color", GRID, None, None, None), "minor_grid": ("bool", False, None, None, None),
    "frame": ("choice", "box", None, None, ["box", "open", "none"]), "frame_width": ("float", 0.8, 0.25, 6, None), "frame_color": ("color", FRAME, None, None, None),
    "tick_dir": ("choice", "out", None, None, ["out", "in", "inout"]), "tick_len": ("float", 3.5, 0, 16, None), "minor_ticks": ("bool", False, None, None, None),
    "legend_pos": ("choice", "best", None, None, [k for k, _ in sh_adv.LEGEND_LOCS]), "legend_frame": ("bool", True, None, None, None),
    "legend_cols": ("float", 1, 1, 8, None),
    "bar_width": ("float", 0.8, 0.1, 1.0, None), "area_alpha": ("float", 0.35, 0.05, 1.0, None),
    "dpi": ("float", 200, 50, 1200, None),
}


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


def blank(chart_id, title="", preset=None):
    """An empty chart.  `preset` is {"style": {...}, "adv": {...}} (the look new charts start from)."""
    ch = {"id": chart_id, "title": title, "type": "line", "swap": False, "stacked": False, "data": {"range": "", "headers": None, "x_col": None, "switch": False},
          "x": "", "x_label": "", "x_units": "", "x_log": False, "x_min": None, "x_max": None,
          "left": axis_def(), "right": axis_def(), "series": [], "limits": [], "zones": [], "notes": [], "grid": True, "legend": True,
          "style": {}, "adv": {}, "pos": [40, 40], "size": list(DEFAULT_SIZE)}
    if preset:
        ch["style"] = copy.deepcopy(preset.get("style") or {})
        ch["adv"] = copy.deepcopy(preset.get("adv") or {})
    return ch


def _qualified(sheet, r1, c1, r2, c2):
    return f"{E.quote_sheet(sheet)}!{E.addr(r1, c1)}:{E.addr(r2, c2)}"


# ------------------------------------------------------------------------------------------------------------------ colours
def palette_colors(ch):
    name = (ch.get("style") or {}).get("palette") or "Default"
    return PALETTES.get(name, PALETTE)


def next_color(ch, i=None):
    cols = palette_colors(ch)
    return cols[(len(ch.get("series", [])) if i is None else i) % len(cols)]


def recolor(ch, palette):
    """Gives the series the colours of a palette (by their place in the list).  No palette name: nothing changes."""
    if palette not in PALETTES:
        return
    cols = PALETTES[palette]
    for i, s in enumerate(ch.get("series", [])):
        s["color"] = cols[i % len(cols)]


# ------------------------------------------------------------------------------------------------------------------ making a chart from cells
_KEEP = ("axis", "style", "color", "width", "linestyle", "marker", "marker_size")


def split_ranges(text):
    """'A1:A5, Sheet2!B1:B5' -> ['A1:A5', 'Sheet2!B1:B5'] (a comma inside a quoted sheet name does not split)."""
    out, cur, quote = [], "", False
    for ch in text or "":
        if ch == "'":
            quote = not quote
        if ch == "," and not quote:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def lines_of(rects, switch=False):
    """The lines of numbers in some blocks: one per column (one per row when `switch`).  A single row of cells is one line along the row."""
    out = []
    for r1, c1, r2, c2 in rects:
        if switch:
            out += [(r, c1, r, c2) for r in range(r1, r2 + 1)]
        elif r1 == r2 and c2 > c1 and len(rects) == 1:
            out.append((r1, c1, r1, c2))
        else:
            out += [(r1, c, r2, c) for c in range(c1, c2 + 1)]
    return out


def build(wb, sheet, ch, rects, headers=None, x_col=None, switch=False):
    """Fills the chart's X range and series from blocks of cells, the way Excel and Google Sheets read a table: a text cell at the top of a line is that line's name,
    and when there are several lines the first one is X.  `headers` / `x_col` None: decided from the cells.  The look of the series that were there stays."""
    ch["data"] = {"range": ", ".join(_qualified(sheet, *a) if (a[0], a[1]) != (a[2], a[3]) else f"{E.quote_sheet(sheet)}!{E.addr(a[0], a[1])}" for a in rects),
                  "headers": headers, "x_col": x_col, "switch": bool(switch)}
    lines = lines_of(rects, switch)
    old = list(ch.get("series", []))
    ch["series"] = []
    ch["x"], ch["x_label"] = "", ""
    if not lines:
        return ch
    horizontal = [a[0] == a[2] and a[3] > a[1] for a in lines]

    def first(a):
        return wb.value(sheet, a[0], a[1])
    probes = [first(a) for a in lines]
    if headers is None:
        longest = max(max(a[2] - a[0], a[3] - a[1]) for a in lines)
        headers = all(isinstance(v, str) for v in probes if v is not None) and any(isinstance(v, str) for v in probes) and longest >= 1 and not (len(lines) == 1 and horizontal[0] and not switch)
    if x_col is None:
        x_col = len(lines) > 1
    ch["data"]["headers"], ch["data"]["x_col"] = bool(headers), bool(x_col)              # what was decided stays decided when the series are read again

    def body(a):
        if not headers:
            return a
        return (a[0], a[1] + 1, a[2], a[3]) if a[0] == a[2] and a[3] > a[1] else (a[0] + 1, a[1], a[2], a[3])

    def name(i):
        return str(probes[i]) if headers and isinstance(probes[i], str) else ""
    ys = list(range(len(lines)))
    if x_col and len(lines) > 1:
        ch["x"] = _qualified(sheet, *body(lines[0]))
        ch["x_label"] = name(0)
        ys = ys[1:]
    else:
        ch["x_label"] = "Point"
    npoints = max(max(body(a)[2] - body(a)[0], body(a)[3] - body(a)[1]) + 1 for a in lines)
    for k, i in enumerate(ys):
        a = body(lines[i])
        if len(ys) == 1:
            style = "both" if horizontal[i] else "line"
        else:
            style = "both" if npoints <= 40 else "line"
        s = {"y": _qualified(sheet, *a), "label": name(i), "axis": "L", "style": style, "color": next_color(ch, k)}
        if k < len(old):
            for key in _KEEP:
                if key in old[k]:
                    s[key] = old[k][key]
        ch["series"].append(s)
    if len(ch["series"]) == 1 and ch["series"][0]["label"] and not ch["left"].get("label"):
        ch["left"]["label"] = ch["series"][0]["label"]
    return ch


def from_selection(wb, sheet, rect, charts=(), preset=None):
    """The chart that Insert chart makes from a highlighted block, the way Excel does for a scatter: the first column is X, every other column is one
    Y series, and a text cell at the top of a column is that series' name.  One column alone is plotted against 1, 2, 3 ...  A block of one row is
    read the same way turned sideways."""
    return from_rects(wb, sheet, [rect], charts, preset)


def from_rects(wb, sheet, rects, charts=(), preset=None, headers=None, x_col=None, switch=False):
    ch = blank(new_id(charts), preset=preset)
    return build(wb, sheet, ch, rects, headers, x_col, switch)


def rebuild(wb, ch, default_sheet=None):
    """Reads the series again from ch["data"] (after the range or an option in it changed).  Returns None, or a plain message when the range is no good."""
    d = ch.get("data") or {}
    parts = split_ranges(d.get("range", ""))
    if not parts:
        return "Pick the cells that hold the data."
    rects, sheet = [], None
    for t in parts:
        p = wb.parse_range(t, default_sheet)
        if p is None:
            return f"'{t}' is not a range of cells."
        if sheet is not None and p[0] != sheet:
            return "Pick cells that are all on one sheet."
        sheet = p[0]
        rects.append(tuple(p[1:]))
    build(wb, sheet, ch, rects, d.get("headers"), d.get("x_col"), d.get("switch", False))
    return None


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


def categories(wb, ch):
    """The words of the X range when it is mostly text (a column of names), else None.  Such an X is drawn as 1, 2, 3 ... with the words under the ticks."""
    if not ch.get("x"):
        return None
    vals = wb.range_values(ch["x"])
    if vals is None:
        return None
    filled = [v for v in vals if v is not None and v != ""]
    if not filled or sum(1 for v in filled if isinstance(v, str)) * 2 <= len(filled):
        return None
    out = []
    for v in vals:
        out.append("" if v is None else (v if isinstance(v, str) else (f"{v:g}" if isinstance(v, float) else str(v))))
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
    """(xs, [(series, ys)]) - the numbers of the chart, every list as long as the shortest range.  xs is 1, 2, 3 ... when the chart has no X range (or its X is words)."""
    sers = []
    for s in ch.get("series", []):
        ys = _nums(wb, s.get("y", ""))
        sers.append((s, ys if ys is not None else []))
    n = min([len(ys) for _s, ys in sers] or [0])
    xs = _nums(wb, ch.get("x", "")) if ch.get("x") else None
    if xs is not None and categories(wb, ch) is not None:
        xs = [float(i + 1) for i in range(len(xs))]
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


# ------------------------------------------------------------------------------------------------------------------ the look
def _color(value, fallback):
    """The colour as matplotlib takes it, or `fallback` when the file holds something that is not a colour."""
    try:
        from matplotlib.colors import is_color_like
        return value if value and is_color_like(value) else fallback
    except Exception:                                          # noqa: BLE001
        return fallback


def style_of(ch):
    """(the chart's basic look with every key present and checked, [notes]).  A value that is not valid is replaced by the default."""
    raw = ch.get("style") if isinstance(ch.get("style"), dict) else {}
    st, notes = {}, []
    for key, (kind, default, lo, hi, choices) in STYLE_SPEC.items():
        v = raw.get(key, default)
        try:
            if kind == "bool":
                v = bool(v)
            elif kind == "float":
                v = max(lo, min(hi, float(v)))
            elif kind == "optfloat":
                v = None if v in (None, "") else max(lo, min(hi, float(v)))
            elif kind == "color":
                if not _color(v, None):
                    raise ValueError
            elif kind == "choice":
                if v not in choices:
                    raise ValueError
            else:
                v = str(v or "")
        except (TypeError, ValueError):
            notes.append(f"The look '{key}' is not valid and was left at its default.")
            v = default
        st[key] = v
    st["legend_cols"] = int(round(st["legend_cols"]))
    return st, notes


def effective_rc(ch, st=None, compact=False):
    """(the matplotlib settings the chart is drawn with, [notes]): the basic look turned into settings, then the advanced "rc:" ones on top."""
    if st is None:
        st = style_of(ch)[0]
    base = 8.0 if compact else 9.0
    tsz = st["title_size"] or base + 2
    lsz = st["label_size"] or base
    ksz = st["tick_size"] or base - 1
    gsz = st["legend_size"] or base - 1
    rc = {"font.size": base, "axes.titlesize": tsz, "axes.titleweight": "bold" if st["title_bold"] else "normal", "axes.titlepad": 8.0,
          "axes.labelsize": lsz, "axes.labelweight": "bold" if st["label_bold"] else "normal",
          "xtick.labelsize": ksz, "ytick.labelsize": ksz, "legend.fontsize": gsz, "legend.title_fontsize": gsz,
          "text.color": st["text_color"], "axes.labelcolor": st["text_color"], "axes.titlecolor": st["text_color"],
          "xtick.color": st["tick_color"], "ytick.color": st["tick_color"], "xtick.labelcolor": st["tick_color"], "ytick.labelcolor": st["tick_color"],
          "axes.edgecolor": st["frame_color"], "axes.linewidth": st["frame_width"], "axes.facecolor": st["plot_bg"], "axes.axisbelow": True, "axes.grid": False,
          "figure.facecolor": st["bg"], "figure.edgecolor": st["bg"], "savefig.facecolor": st["bg"],
          "lines.linewidth": st["line_width"], "lines.markersize": st["marker_size"],
          "grid.color": st["grid_color"], "grid.linewidth": st["grid_width"], "grid.linestyle": sh_adv.mpl_linestyle(st["grid_style"]),
          "xtick.direction": st["tick_dir"], "ytick.direction": st["tick_dir"], "xtick.major.size": st["tick_len"], "ytick.major.size": st["tick_len"],
          "xtick.minor.size": st["tick_len"] * 0.55, "ytick.minor.size": st["tick_len"] * 0.55,
          "legend.frameon": st["legend_frame"], "legend.framealpha": 0.92, "legend.edgecolor": FRAME, "legend.facecolor": "inherit", "legend.fancybox": True}
    if st["font"]:
        rc["font.family"] = [st["font"]]
    extra, notes = sh_adv.rc_values(ch.get("adv"))
    rc.update(extra)
    try:
        import matplotlib as mpl
        rc = {k: v for k, v in rc.items() if k in mpl.rcParams}          # (a setting this matplotlib does not have is left out)
    except ImportError:
        pass
    return rc, notes


# ------------------------------------------------------------------------------------------------------------------ drawing
class _Group:
    """Several matplotlib artists that are set together (the bars of one series)."""

    def __init__(self, artists):
        self.artists = [a for a in artists if a is not None]

    def set(self, **kw):
        for a in self.artists:
            a.set(**kw)


def _number(v, fallback):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else fallback


def _axis(a, dep, swapped):
    """The matplotlib axis that carries the dependent (dep=True) or the independent values."""
    return a.xaxis if dep == swapped else a.yaxis


def _label(a, dep, swapped, text):
    (a.set_xlabel if dep == swapped else a.set_ylabel)(text)


def _scale(a, dep, swapped, which):
    (a.set_xscale if dep == swapped else a.set_yscale)(which)


def _lim(a, dep, swapped, lo, hi):
    cur = a.get_xlim() if dep == swapped else a.get_ylim()
    new = (lo if lo is not None else cur[0], hi if hi is not None else cur[1])
    if new[0] != new[1]:
        (a.set_xlim if dep == swapped else a.set_ylim)(*new)


def _draw(fig, wb, ch, st, rc, compact, notes):
    ctype = ch.get("type") if ch.get("type") in dict(TYPES) else "line"
    swapped = bool(ch.get("swap")) != (ctype == "bar")
    adv = ch.get("adv") or {}
    fig.patch.set_facecolor(rc.get("figure.facecolor", "white"))
    fig.patch.set_edgecolor(rc.get("figure.edgecolor", "white"))
    ax = fig.add_subplot(111)
    ax2 = None
    xs, sers = data(wb, ch)
    cats = categories(wb, ch)
    fs = _number(rc.get("font.size"), 9.0)
    right_used = any(s.get("axis") == "R" for s, _ys in sers) or any(g.get("axis") == "R" for k in ("limits", "zones", "notes") for g in ch.get(k, []))
    if right_used:
        ax2 = ax.twiny() if swapped else ax.twinx()
        if swapped:
            ax2._sh_second_x = True
        else:
            ax2._sh_second_y = True
    axes = {"L": ax, "R": ax2 or ax}
    lines = [None] * len(sers)
    shapes = [None] * len(sers)
    handles = []
    stacked = bool(ch.get("stacked")) and ctype in ("column", "bar", "area")
    base = {"L": [0.0] * len(xs), "R": [0.0] * len(xs)}
    X = [x if x is not None else math.nan for x in xs]
    spacing = 1.0
    real = sorted(x for x in xs if x is not None)
    if len(real) > 1:
        d = sorted({abs(b - a) for a, b in zip(real, real[1:]) if b != a})
        spacing = d[0] if d else 1.0
    bars_n = max(1, len(sers))
    for i, (s, ys) in enumerate(sers):
        key = "R" if s.get("axis") == "R" else "L"
        a = axes[key]
        color = _color(s.get("color"), palette_colors(ch)[i % len(palette_colors(ch))])
        label = s.get("label") or f"Series {i + 1}"
        mode = "markers" if ctype == "scatter" else s.get("style", "line")
        lw = _number(s.get("width"), st["line_width"])
        ls_key = s.get("linestyle") or (AUTO_DASH[i % len(AUTO_DASH)] if st["auto_dash"] else st["line_style"])
        marker = s.get("marker") or (AUTO_MARK[i % len(AUTO_MARK)] if st["auto_dash"] else st["marker"])
        ms = _number(s.get("marker_size"), st["marker_size"])
        Y = [y if y is not None else math.nan for y in ys]
        if ctype in ("column", "bar"):
            w = st["bar_width"] * spacing / (1 if stacked else bars_n)
            off = 0.0 if stacked else (i - (bars_n - 1) / 2.0) * w
            pos = [x + off for x in X]
            h = [0.0 if y != y else y for y in Y]
            bottom = list(base[key]) if stacked else None
            if swapped:
                cont = a.barh(pos, h, height=w, left=bottom, color=color, label=label)
            else:
                cont = a.bar(pos, h, width=w, bottom=bottom, color=color, label=label)
            if stacked:
                base[key] = [b + v for b, v in zip(base[key], h)]
            shapes[i] = _Group(list(cont.patches))
            handles.append(cont)
            continue
        if ctype == "area":
            h = [0.0 if y != y else y for y in Y]
            lo = list(base[key]) if stacked else [0.0] * len(X)
            hi = [b + v for b, v in zip(lo, h)] if stacked else h
            poly = (a.fill_betweenx(X, lo, hi, color=color, alpha=st["area_alpha"], linewidth=0) if swapped
                    else a.fill_between(X, lo, hi, color=color, alpha=st["area_alpha"], linewidth=0))
            if stacked:
                base[key] = hi
            shapes[i] = _Group([poly])
            YY = hi
        else:
            YY = Y
        line_on = mode in ("line", "both") or ctype in ("area",)
        marks_on = mode in ("markers", "both") and ctype != "area" and marker != "none"
        args = (YY, X) if swapped else (X, YY)
        line, = a.plot(*args, color=color, linewidth=lw, linestyle=sh_adv.mpl_linestyle(ls_key) if line_on else "None", marker=marker if marks_on else None,
                       markersize=ms, label=label, drawstyle="steps-mid" if ctype == "step" else "default")
        lines[i] = line
        handles.append(line)

    guide_lines, guide_zones, guide_notes = [], [], []

    for g in ch.get("zones", []):
        lo, hi = resolve(wb, g.get("lo")), resolve(wb, g.get("hi"))
        if lo is None or hi is None:
            continue
        lo, hi = min(lo, hi), max(lo, hi)
        color = _color(g.get("color"), "#e8590c")
        indep = g.get("axis") == "X"
        a = ax if indep else axes["R" if g.get("axis") == "R" else "L"]
        across_x = indep != swapped                            # the band runs up and down (a vertical band) when this is True
        span = a.axvspan(lo, hi, color=color, alpha=0.14, linewidth=0) if across_x else a.axhspan(lo, hi, color=color, alpha=0.14, linewidth=0)
        guide_zones.append(span)
        if g.get("label"):
            if across_x:
                a.text((lo + hi) / 2, 0.98, g["label"], transform=a.get_xaxis_transform(), ha="center", va="top", fontsize=fs - 1, color=color)
            else:
                a.text(0.015, (lo + hi) / 2, g["label"], transform=a.get_yaxis_transform(), ha="left", va="center", fontsize=fs - 1, color=color)
    for g in ch.get("limits", []):
        v = resolve(wb, g.get("value"))
        if v is None:
            continue
        color = _color(g.get("color"), "#c0392b")
        indep = g.get("axis") == "X"
        a = ax if indep else axes["R" if g.get("axis") == "R" else "L"]
        across_x = indep != swapped
        ln = a.axvline(v, color=color, linestyle="--", linewidth=1.2) if across_x else a.axhline(v, color=color, linestyle="--", linewidth=1.2)
        guide_lines.append(ln)
        if g.get("label"):
            if across_x:
                a.text(v, 0.02, " " + g["label"], transform=a.get_xaxis_transform(), ha="left", va="bottom", fontsize=fs - 1, color=color)
            else:
                a.text(0.99, v, g["label"] + " ", transform=a.get_yaxis_transform(), ha="right", va="bottom", fontsize=fs - 1, color=color)
    for g in ch.get("notes", []):
        x, y = resolve(wb, g.get("x")), resolve(wb, g.get("y"))
        if x is None or y is None or not g.get("text"):
            continue
        a = axes["R" if g.get("axis") == "R" else "L"]
        xy = (y, x) if swapped else (x, y)
        guide_notes.append(a.annotate(g["text"], xy=xy, xytext=(14, 18), textcoords="offset points", fontsize=fs - 0.5, color=INK,
                                      arrowprops={"arrowstyle": "->", "color": MUTED, "linewidth": 0.9},
                                      bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": FRAME, "lw": 0.8}))
    if not ch.get("series"):
        ax.text(0.5, 0.5, "Choose the data in the panel", transform=ax.transAxes, ha="center", va="center", color=MUTED, fontsize=fs)

    _label(ax, False, swapped, axis_title(ch.get("x_label"), ch.get("x_units")))
    _label(ax, True, swapped, axis_title(ch.get("left", {}).get("label"), ch.get("left", {}).get("units")))
    if ax2 is not None:
        _label(ax2, True, swapped, axis_title(ch.get("right", {}).get("label"), ch.get("right", {}).get("units")))
    if ch.get("x_log"):
        _scale(ax, False, swapped, "log")
    elif not ch.get("x") or cats is not None:                  # 1, 2, 3 ... : whole numbers only
        from matplotlib.ticker import MaxNLocator
        _axis(ax, False, swapped).set_major_locator(MaxNLocator(integer=True))
    if cats is not None and xs:
        axis = _axis(ax, False, swapped)
        axis.set_ticks(xs)
        axis.set_ticklabels(cats[:len(xs)])
        if not swapped and max(len(c) for c in cats[:len(xs)] + [""]) > 6:
            for t in ax.get_xticklabels():
                t.set_rotation(30)
                t.set_ha("right")
    if ch.get("left", {}).get("log"):
        _scale(ax, True, swapped, "log")
    if ax2 is not None and ch.get("right", {}).get("log"):
        _scale(ax2, True, swapped, "log")
    _lim_val = lambda v: resolve(wb, v)                        # noqa: E731
    _lim(ax, False, swapped, _lim_val(ch.get("x_min")), _lim_val(ch.get("x_max")))
    _lim(ax, True, swapped, _lim_val(ch.get("left", {}).get("min")), _lim_val(ch.get("left", {}).get("max")))
    if ax2 is not None:
        _lim(ax2, True, swapped, _lim_val(ch.get("right", {}).get("min")), _lim_val(ch.get("right", {}).get("max")))
    if ch.get("title"):
        ax.set_title(ch["title"])

    # ---- ticks, grid, frame (set outright, so the picture does not depend on matplotlib's settings at the moment it is painted)
    every = [ax] + ([ax2] if ax2 is not None else [])
    for a in every:
        a.tick_params(which="major", direction=st["tick_dir"], length=st["tick_len"], labelsize=_number(rc.get("xtick.labelsize"), fs - 1), colors=st["tick_color"])
        a.tick_params(which="minor", direction=st["tick_dir"], length=st["tick_len"] * 0.55, colors=st["tick_color"])
        if st["minor_ticks"]:
            a.minorticks_on()
    mode = st["grid"] if ch.get("grid", True) else "none"
    ax.xaxis.grid(mode in ("both", "vertical"), which="major")
    ax.yaxis.grid(mode in ("both", "horizontal"), which="major")
    if st["minor_grid"] and mode != "none":
        ax.minorticks_on()
        ax.grid(True, which="minor", color=st["grid_color"], linewidth=max(0.3, st["grid_width"] * 0.6), linestyle=":")
    ax.set_axisbelow(True)
    if st["frame"] != "box":
        hide = {"top", "right"} if st["frame"] == "open" else {"top", "right", "left", "bottom"}
        if ax2 is not None and st["frame"] == "open":
            hide.discard("top" if swapped else "right")
        for a in every:
            for side in hide:
                a.spines[side].set_visible(False)

    # ---- the legend
    leg_kw = {"loc": st["legend_pos"], "ncol": st["legend_cols"]}
    layout = {"tight": True, "pad": 0.9, "left": 0.12, "right": 0.95, "bottom": 0.12, "top": 0.92}
    targets = {"figure": [fig], "axes": every, "title": [ax.title], "xaxis": [ax.xaxis], "yaxis": [ax.yaxis],
               "yaxis2": [ax2.yaxis] if ax2 is not None and not swapped else [], "xaxis2": [ax2.xaxis] if ax2 is not None and swapped else [],
               "spines": every, "series": lines, "bars": shapes, "limits": guide_lines, "zones": guide_zones, "notes": guide_notes,
               "legend": [leg_kw], "layout": [layout]}
    sh_adv.apply_objects(adv, targets, notes, only=("legend", "layout"))
    show_legend = ch.get("legend", True) and len(handles) > 0 and (len(handles) > 1 or any(s.get("label") for s, _ in sers))
    if show_legend:
        kw = dict(leg_kw)
        ax_x, ax_y = kw.pop("anchor_x", None), kw.pop("anchor_y", None)
        loc = kw.get("loc", "best")
        outside = {"outside right": ("center left", (1.02, 0.5)), "outside bottom": ("upper center", (0.5, -0.16)), "outside top": ("lower center", (0.5, 1.02))}
        if loc in outside:
            kw["loc"], kw["bbox_to_anchor"] = outside[loc]
        if ax_x is not None and ax_y is not None:
            kw["bbox_to_anchor"] = (ax_x, ax_y)
        if kw.get("mode") == "none":
            kw.pop("mode")
        try:
            ax.legend(handles=handles, **kw)
        except (TypeError, ValueError, AttributeError) as ex:
            notes.append(f"Legend: {str(ex).splitlines()[0][:90] if str(ex) else 'a setting was refused'}")
            try:
                ax.legend(handles=handles, loc="best")
            except (TypeError, ValueError):
                pass
    sh_adv.apply_objects(adv, targets, notes, skip=("legend", "layout"))
    try:
        if layout["tight"]:
            fig.tight_layout(pad=_number(layout["pad"], 0.9))
        else:
            fig.subplots_adjust(left=layout["left"], right=layout["right"], bottom=layout["bottom"], top=layout["top"])
    except (ValueError, RuntimeError):
        pass


def draw(fig, wb, ch, compact=False):
    """Draws the chart onto a matplotlib Figure (it is cleared first).  Never raises for bad data: it draws what it can; fig.sh_notes holds plain notes about what
    could not be done (a setting matplotlib refused ...)."""
    fig.clear()
    notes = []
    fig.sh_notes = notes
    fig.patch.set_facecolor("white")
    mpl = sh_deps.matplotlib()
    if mpl is None:
        return fig
    st, n1 = style_of(ch)
    rc, n2 = effective_rc(ch, st, compact)
    notes.extend(n1 + n2)
    try:
        with mpl.rc_context(rc):
            _draw(fig, wb, ch, st, rc, compact, notes)
    except Exception as ex:                                   # noqa: BLE001 - a chart that cannot be drawn completely still shows what it has
        notes.append(f"The chart could not be drawn completely: {str(ex).splitlines()[0][:100] if str(ex) else type(ex).__name__}")
    return fig


def notes(wb, ch):
    """The plain notes that drawing this chart leaves (a scratch drawing; nothing is shown).  Used by the panel to say what matplotlib refused."""
    mpl = sh_deps.matplotlib()
    if mpl is None:
        return []
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(4, 3), dpi=50)
    FigureCanvasAgg(fig)
    draw(fig, wb, ch)
    out = list(getattr(fig, "sh_notes", []))
    try:
        fig.canvas.draw()                                      # what only shows when the picture is made is found here too
    except Exception as ex:                                    # noqa: BLE001
        out.append(f"The chart could not be drawn: {str(ex).splitlines()[0][:100] if str(ex) else type(ex).__name__}")
    return out


def figure(wb, ch, size_px=None, dpi=100):
    """A matplotlib Figure with the chart drawn (no pyplot, so nothing keeps it alive); None when matplotlib is missing."""
    if sh_deps.matplotlib() is None:
        return None
    from matplotlib.figure import Figure
    w, h = size_px or ch.get("size") or DEFAULT_SIZE
    fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    draw(fig, wb, ch)
    return fig


def export(wb, ch, path, size_px=(1000, 650), dpi=None):
    """Writes the chart as PNG, SVG or PDF (by the file name's ending).  Returns None, or a plain message when it did not work."""
    ext = str(path).rsplit(".", 1)[-1].lower()
    if ext not in FILE_TYPES:
        return "Choose a file name ending in .png, .svg or .pdf."
    fig = figure(wb, ch, size_px, dpi=100)
    if fig is None:
        return "matplotlib is needed to draw charts."
    st, _n = style_of(ch)
    rc, _n2 = effective_rc(ch, st)
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig)
        use_dpi = dpi if dpi is not None else (_number(rc.get("savefig.dpi"), 0) or st["dpi"])
        kw = {"dpi": use_dpi if ext == "png" else 100, "format": ext, "facecolor": fig.get_facecolor()}
        if rc.get("savefig.transparent"):
            kw["transparent"] = True
        if rc.get("savefig.bbox") == "tight":
            kw["bbox_inches"] = "tight"
            kw["pad_inches"] = _number(rc.get("savefig.pad_inches"), 0.1)
        fig.savefig(path, **kw)
    except Exception as ex:                                    # noqa: BLE001 - a file that cannot be written, or a setting that cannot be drawn: a message, not a crash
        return f"The chart could not be written: {str(ex).splitlines()[0][:120] if str(ex) else type(ex).__name__}"
    return None


def copy_chart(ch, charts):
    c = copy.deepcopy(ch)
    c["id"] = new_id(charts)
    c["pos"] = [ch.get("pos", [40, 40])[0] + 24, ch.get("pos", [40, 40])[1] + 24]
    return c
