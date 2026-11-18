"""
sh_adv.py - the Advanced chart options: what matplotlib can change, as a list of inputs (no code box anywhere).

Two kinds of property, both kept in a chart's `adv` dictionary under a text key:

    "rc:axes.titlesize"        a matplotlib setting that applies to the whole chart ("matplotlib defaults"; the list is read from matplotlib itself, so it follows the
                               version that is installed)
    "legend:loc"               a property of one part of the chart (the figure, the axes, the title, each axis, the frame, the legend, the series, the bars, the guides ...)
    "series[2]:linewidth"      the same for one series only (the number is the series' place in the list, from 0)

    props()  /  get(key)       the property table (Prop objects: label, group, kind, bounds, choices, default)
    coerce(prop, raw)          (ok, value, message): the typed value, checked and kept inside its bounds; value None means "not set" for the optional kinds
    rc_values(adv)             ({matplotlib key: value} that matplotlib accepts, [notes about the ones it refused])
    apply_objects(adv, targets, notes, only=None)     sets the object properties on what the chart drew; a property that fails only adds a note

Every input is a typed value (number inside bounds, a choice from a list, a colour, a switch, a short text), so a workbook that is opened can never run anything.
"""
import re

KINDS = ("bool", "int", "float", "optint", "optfloat", "color", "choice", "text", "fontsize")

LINESTYLES = [("-", "Solid"), ("--", "Dashed"), (":", "Dotted"), ("-.", "Dash-dot"), ("longdash", "Long dash"), ("densedots", "Dense dots"), ("dashdotdot", "Dash-dot-dot")]
_STYLE_TUPLES = {"longdash": (0, (10, 4)), "densedots": (0, (1, 1.3)), "dashdotdot": (0, (6, 2, 1, 2, 1, 2))}
MARKERS = [("none", "None"), ("o", "Circle"), ("s", "Square"), ("^", "Triangle up"), ("v", "Triangle down"), ("<", "Triangle left"), (">", "Triangle right"),
           ("D", "Diamond"), ("d", "Thin diamond"), ("P", "Plus (filled)"), ("X", "Cross (filled)"), ("*", "Star"), ("p", "Pentagon"), ("h", "Hexagon"),
           ("+", "Plus"), ("x", "Cross"), (".", "Point"), ("|", "Vertical bar"), ("_", "Horizontal bar")]
WEIGHTS = [("normal", "Normal"), ("bold", "Bold"), ("light", "Light"), ("semibold", "Semibold"), ("heavy", "Heavy")]
FONTSTYLES = [("normal", "Normal"), ("italic", "Italic"), ("oblique", "Oblique")]
LEGEND_LOCS = [("best", "Best"), ("upper right", "Upper right"), ("upper left", "Upper left"), ("lower left", "Lower left"), ("lower right", "Lower right"),
               ("right", "Right"), ("center left", "Centre left"), ("center right", "Centre right"), ("lower center", "Lower centre"), ("upper center", "Upper centre"),
               ("center", "Centre"), ("outside right", "Outside right"), ("outside bottom", "Outside bottom"), ("outside top", "Outside top")]
CAPS = [("butt", "Butt"), ("round", "Round"), ("projecting", "Projecting")]
JOINS = [("miter", "Miter"), ("round", "Round"), ("bevel", "Bevel")]
DRAWSTYLES = [("default", "Straight"), ("steps-pre", "Steps (pre)"), ("steps-mid", "Steps (mid)"), ("steps-post", "Steps (post)")]
FILLSTYLES = [("full", "Full"), ("left", "Left half"), ("right", "Right half"), ("bottom", "Bottom half"), ("top", "Top half"), ("none", "Hollow")]
HATCHES = [("", "None"), ("/", "Slash"), ("\\", "Backslash"), ("|", "Vertical"), ("-", "Horizontal"), ("+", "Cross"), ("x", "Diagonal cross"), ("o", "Circles"),
           (".", "Dots"), ("*", "Stars"), ("//", "Dense slash"), ("xx", "Dense cross")]
SCALES = [("linear", "Linear"), ("log", "Log"), ("symlog", "Symmetric log")]
TICKDIRS = [("out", "Out"), ("in", "In"), ("inout", "Both")]
TICKFORMATS = [("auto", "Automatic"), ("plain", "Plain numbers"), ("scientific", "Scientific"), ("engineering", "Engineering (k, M, m)"), ("percent", "Percent (1 = 100%)"),
               ("percent100", "Percent (100 = 100%)"), ("thousands", "Thousands separator"), ("hidden", "No labels")]
MINORS = [("0", "None"), ("2", "1 between"), ("3", "2 between"), ("4", "3 between"), ("5", "4 between"), ("10", "9 between")]
AXISBELOW = [("true", "Below everything"), ("line", "Below lines"), ("false", "Above")]
ARROWS = [("->", "Open"), ("-|>", "Filled"), ("<->", "Both ends"), ("-", "Line only"), ("fancy", "Fancy"), ("simple", "Simple"), ("wedge", "Wedge")]
BOXES = [("none", "No box"), ("round", "Round"), ("square", "Square"), ("round4", "Round (big)"), ("sawtooth", "Saw tooth")]
MODES = [("none", "Normal"), ("expand", "Fill the width")]
TITLELOCS = [("center", "Centre"), ("left", "Left"), ("right", "Right")]
ASPECTS = [("auto", "Fill the box"), ("equal", "Equal scale")]
ALIGNS = [("center", "Centre"), ("left", "Left"), ("right", "Right")]


def mpl_linestyle(key):
    """The matplotlib linestyle for a choice key (the few that are dash patterns are tuples)."""
    return _STYLE_TUPLES.get(key, key)


class Prop:
    __slots__ = ("key", "target", "name", "label", "group", "kind", "default", "lo", "hi", "choices", "apply", "preset", "tip", "step")

    def __init__(self, target, name, label, group, kind, default=None, lo=None, hi=None, choices=None, apply=None, preset=True, tip="", step=None):
        self.target, self.name, self.label, self.group, self.kind = target, name, label, group, kind
        self.key = f"{target}:{name}"
        self.default, self.lo, self.hi, self.choices, self.apply, self.preset, self.tip, self.step = default, lo, hi, choices, apply, preset, tip, step


# ------------------------------------------------------------------------------------------------------------------ applying one value
def _set(**names):
    """An apply function that calls artist.set(property=value) for each name given (the property name is the key of `names`, its argument the value)."""
    def apply(objs, v):
        for o in objs:
            if o is not None:
                o.set(**{n: v for n in names})
    return apply


def _setp(prop, conv=None):
    def apply(objs, v):
        for o in objs:
            if o is not None:
                o.set(**{prop: conv(v) if conv else v})
    return apply


def _call(method, conv=None):
    def apply(objs, v):
        for o in objs:
            if o is not None:
                getattr(o, method)(conv(v) if conv else v)
    return apply


def _ls(v):
    return mpl_linestyle(v)


def _tick(which, key, conv=None):
    """Axis.set_tick_params(which=..., key=value)."""
    def apply(objs, v):
        for axis in objs:
            axis.set_tick_params(which=which, **{key: conv(v) if conv else v})
    return apply


def _axis_is_x(axis):
    return axis is axis.axes.xaxis


def _axis_scale(objs, v):
    for axis in objs:
        (axis.axes.set_xscale if _axis_is_x(axis) else axis.axes.set_yscale)(v)


def _axis_invert(objs, v):
    for axis in objs:
        ax = axis.axes
        lo, hi = (ax.get_xlim() if _axis_is_x(axis) else ax.get_ylim())
        new = (max(lo, hi), min(lo, hi)) if v else (min(lo, hi), max(lo, hi))
        (ax.set_xlim if _axis_is_x(axis) else ax.set_ylim)(*new)


def _axis_grid(which):
    def apply(objs, v):
        for axis in objs:
            axis.grid(bool(v), which=which)
    return apply


def _axis_grid_look(which, key, conv=None):
    return _tick(which, "grid_" + key, conv)


def _minor_count(objs, v):
    from matplotlib.ticker import AutoMinorLocator, NullLocator
    n = int(v)
    for axis in objs:
        axis.set_minor_locator(AutoMinorLocator(n) if n >= 2 else NullLocator())


def _tick_step(objs, v):
    from matplotlib.ticker import MultipleLocator
    step = float(v)
    for axis in objs:
        lo, hi = axis.get_view_interval()
        if step <= 0 or abs(hi - lo) / step > 400:
            raise ValueError("the step is too small for the range of the axis (more than 400 ticks)")
        axis.set_major_locator(MultipleLocator(step))


def _tick_max(objs, v):
    from matplotlib.ticker import MaxNLocator
    for axis in objs:
        axis.set_major_locator(MaxNLocator(nbins=int(v)))


def _tick_format(objs, v):
    import matplotlib.ticker as T
    for axis in objs:
        if v == "plain":
            f = T.ScalarFormatter(useOffset=False)
            f.set_scientific(False)
        elif v == "scientific":
            f = T.ScalarFormatter()
            f.set_scientific(True)
            f.set_powerlimits((0, 0))
        elif v == "engineering":
            f = T.EngFormatter()
        elif v == "percent":
            f = T.PercentFormatter(xmax=1)
        elif v == "percent100":
            f = T.PercentFormatter(xmax=100)
        elif v == "thousands":
            f = T.FuncFormatter(lambda x, _p: f"{x:,.10g}")
        elif v == "hidden":
            f = T.NullFormatter()
        else:
            f = T.ScalarFormatter()
        axis.set_major_formatter(f)


def _tick_decimals(objs, v):
    from matplotlib.ticker import FormatStrFormatter
    for axis in objs:
        axis.set_major_formatter(FormatStrFormatter(f"%.{int(v)}f"))


def _axis_label(prop, conv=None):
    def apply(objs, v):
        for axis in objs:
            axis.label.set(**{prop: conv(v) if conv else v})
    return apply


def _axis_labelpad(objs, v):
    for axis in objs:
        axis.labelpad = float(v)


def _axis_visible(objs, v):
    for axis in objs:
        axis.set_visible(bool(v))


def _axes_axisbelow(objs, v):
    for ax in objs:
        ax.set_axisbelow({"true": True, "false": False, "line": "line"}[v])


def _axes_aspect(objs, v):
    for ax in objs[:1]:
        ax.set_aspect(v)


def _margin(which):
    def apply(objs, v):
        for ax in objs:
            (ax.set_xmargin if which == "x" else ax.set_ymargin)(float(v))
    return apply


def _title_place(attr):
    """Title location / distance: the title text moves to the other slot and keeps its words."""
    def apply(objs, v):
        for t in objs:
            ax = getattr(t, "axes", None)
            if ax is None:
                continue
            text = ax.get_title("center") or ax.get_title("left") or ax.get_title("right")
            if attr == "loc":
                for slot in ("center", "left", "right"):
                    ax.set_title("", loc=slot)
                ax.set_title(text, loc=v)
            else:
                ax.set_title(text, pad=float(v))
    return apply


def _spine(side, prop, conv=None):
    def apply(objs, v):
        for ax in objs:
            sp = ax.spines.get(side)
            if sp is None:
                continue
            if prop == "outward":
                sp.set_position(("outward", float(v)))
            elif prop == "visible":
                sp.set_visible(bool(v))
            else:
                sp.set(**{prop: conv(v) if conv else v})
    return apply


def _marker(v):
    return "None" if v == "none" else v


def _hatch(v):
    return v or None


def _arrow(prop):
    def apply(objs, v):
        for a in objs:
            patch = getattr(a, "arrow_patch", None)
            if patch is None:
                continue
            if prop == "style":
                patch.set_arrowstyle(v)
            elif prop == "color":
                patch.set_color(v)
            else:
                patch.set_linewidth(float(v))
    return apply


def _box(prop):
    def apply(objs, v):
        for a in objs:
            patch = a.get_bbox_patch()
            if prop == "style":
                if v == "none":
                    a.set_bbox(None)
                elif patch is not None:
                    patch.set_boxstyle(v)
                else:
                    a.set_bbox({"boxstyle": v, "fc": "white", "ec": "#c8d0de"})
            elif patch is not None:
                (patch.set_facecolor if prop == "face" else patch.set_edgecolor)(v)
    return apply


def _kw(name):
    """A legend / layout property: it goes into the dictionary the chart builds its legend (or layout) from."""
    def apply(objs, v):
        for d in objs:
            d[name] = v
    return apply


# ------------------------------------------------------------------------------------------------------------------ the object properties
def _object_props():
    out = []
    add = out.append
    P = Prop

    g = "Figure"
    add(P("figure", "facecolor", "Background", g, "color", "#ffffff", apply=_setp("facecolor")))
    add(P("figure", "edgecolor", "Border colour", g, "color", "#ffffff", apply=_setp("edgecolor")))
    add(P("figure", "linewidth", "Border width", g, "float", 0.0, 0, 10, apply=_setp("linewidth", float), step=0.5))
    add(P("figure", "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))

    g = "Layout"
    add(P("layout", "tight", "Fit the chart to its box", g, "bool", True, apply=_kw("tight")))
    add(P("layout", "pad", "Space round the chart", g, "float", 0.9, 0, 5, apply=_kw("pad"), step=0.1))
    for side, lo, hi, dflt in (("left", 0, 0.9, 0.12), ("right", 0.1, 1, 0.95), ("bottom", 0, 0.9, 0.12), ("top", 0.1, 1, 0.92)):
        add(P("layout", side, f"{side.capitalize()} edge (fraction, when not fitted)", g, "float", dflt, lo, hi, apply=_kw(side), step=0.01))

    g = "Plot area"
    add(P("axes", "facecolor", "Background", g, "color", "#ffffff", apply=_setp("facecolor")))
    add(P("axes", "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))
    add(P("axes", "frame_on", "Draw the frame", g, "bool", True, apply=_setp("frame_on")))
    add(P("axes", "axisbelow", "Grid and axes drawn", g, "choice", "true", choices=AXISBELOW, apply=_axes_axisbelow))
    add(P("axes", "aspect", "Scale of X and Y", g, "choice", "auto", choices=ASPECTS, apply=_axes_aspect))
    add(P("axes", "xmargin", "Room round the data, X (fraction)", g, "float", 0.05, 0, 1, apply=_margin("x"), step=0.01))
    add(P("axes", "ymargin", "Room round the data, Y (fraction)", g, "float", 0.05, 0, 1, apply=_margin("y"), step=0.01))

    g = "Title"
    add(P("title", "fontsize", "Size", g, "float", 11, 4, 72, apply=_setp("fontsize", float), step=0.5))
    add(P("title", "fontweight", "Weight", g, "choice", "bold", choices=WEIGHTS, apply=_setp("fontweight")))
    add(P("title", "fontstyle", "Style", g, "choice", "normal", choices=FONTSTYLES, apply=_setp("fontstyle")))
    add(P("title", "color", "Colour", g, "color", "#1f2a3c", apply=_setp("color")))
    add(P("title", "backgroundcolor", "Background", g, "color", "#ffffff", apply=_setp("backgroundcolor")))
    add(P("title", "rotation", "Rotation (degrees)", g, "float", 0, -180, 180, apply=_setp("rotation", float), step=5))
    add(P("title", "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))
    add(P("title", "loc", "Place", g, "choice", "center", choices=TITLELOCS, apply=_title_place("loc")))
    add(P("title", "pad", "Distance from the plot (pt)", g, "float", 8, 0, 80, apply=_title_place("pad"), step=1))
    add(P("title", "visible", "Show", g, "bool", True, apply=_setp("visible")))

    for target, title in (("xaxis", "Bottom axis"), ("yaxis", "Left axis"), ("yaxis2", "Right axis"), ("xaxis2", "Top axis")):
        out.extend(_axis_props(target, title))

    g = "Frame (the four sides)"
    for side in ("left", "right", "top", "bottom"):
        s = side.capitalize()
        add(P("spines", f"{side}.visible", f"{s}: show", g, "bool", True, apply=_spine(side, "visible")))
        add(P("spines", f"{side}.linewidth", f"{s}: width", g, "float", 0.8, 0, 10, apply=_spine(side, "linewidth", float), step=0.25))
        add(P("spines", f"{side}.color", f"{s}: colour", g, "color", "#c8d0de", apply=_spine(side, "edgecolor")))
        add(P("spines", f"{side}.linestyle", f"{s}: line style", g, "choice", "-", choices=LINESTYLES, apply=_spine(side, "linestyle", _ls)))
        add(P("spines", f"{side}.alpha", f"{s}: opacity", g, "float", 1.0, 0, 1, apply=_spine(side, "alpha", float), step=0.05))
        add(P("spines", f"{side}.outward", f"{s}: moved out (pt)", g, "float", 0, -40, 80, apply=_spine(side, "outward"), step=1))

    g = "Legend"
    L = "legend"
    add(P(L, "loc", "Place", g, "choice", "best", choices=LEGEND_LOCS, apply=_kw("loc")))
    add(P(L, "ncol", "Columns", g, "int", 1, 1, 10, apply=_kw("ncol")))
    add(P(L, "fontsize", "Text size", g, "float", 8, 4, 40, apply=_kw("fontsize"), step=0.5))
    add(P(L, "labelcolor", "Text colour", g, "color", "#1f2a3c", apply=_kw("labelcolor")))
    add(P(L, "frameon", "Frame", g, "bool", True, apply=_kw("frameon")))
    add(P(L, "framealpha", "Frame opacity", g, "float", 0.92, 0, 1, apply=_kw("framealpha"), step=0.05))
    add(P(L, "facecolor", "Frame fill", g, "color", "#ffffff", apply=_kw("facecolor")))
    add(P(L, "edgecolor", "Frame colour", g, "color", "#c8d0de", apply=_kw("edgecolor")))
    add(P(L, "fancybox", "Round corners", g, "bool", True, apply=_kw("fancybox")))
    add(P(L, "shadow", "Shadow", g, "bool", False, apply=_kw("shadow")))
    add(P(L, "title", "Title", g, "text", "", apply=_kw("title"), preset=False))
    add(P(L, "title_fontsize", "Title size", g, "float", 9, 4, 40, apply=_kw("title_fontsize"), step=0.5))
    add(P(L, "markerscale", "Marker size (times)", g, "float", 1.0, 0.1, 5, apply=_kw("markerscale"), step=0.1))
    add(P(L, "labelspacing", "Space between entries", g, "float", 0.5, 0, 3, apply=_kw("labelspacing"), step=0.1))
    add(P(L, "handlelength", "Sample line length", g, "float", 2.0, 0, 10, apply=_kw("handlelength"), step=0.25))
    add(P(L, "handletextpad", "Sample to text", g, "float", 0.8, 0, 5, apply=_kw("handletextpad"), step=0.1))
    add(P(L, "borderpad", "Space inside the frame", g, "float", 0.4, 0, 3, apply=_kw("borderpad"), step=0.1))
    add(P(L, "columnspacing", "Space between columns", g, "float", 2.0, 0, 5, apply=_kw("columnspacing"), step=0.1))
    add(P(L, "borderaxespad", "Distance from the plot", g, "float", 0.5, 0, 3, apply=_kw("borderaxespad"), step=0.1))
    add(P(L, "numpoints", "Points per line sample", g, "int", 1, 1, 5, apply=_kw("numpoints")))
    add(P(L, "mode", "Width", g, "choice", "none", choices=MODES, apply=_kw("mode")))
    add(P(L, "alignment", "Title and entries", g, "choice", "center", choices=ALIGNS, apply=_kw("alignment")))
    add(P(L, "reverse", "Reverse the order", g, "bool", False, apply=_kw("reverse")))
    add(P(L, "anchor_x", "Anchor X (fraction of the plot)", g, "optfloat", None, -0.5, 1.5, apply=_kw("anchor_x"), step=0.05))
    add(P(L, "anchor_y", "Anchor Y (fraction of the plot)", g, "optfloat", None, -0.5, 1.5, apply=_kw("anchor_y"), step=0.05))

    g = "Series (lines)"
    S = "series"
    add(P(S, "color", "Colour", g, "color", "#2b7de9", apply=_setp("color")))
    add(P(S, "linewidth", "Width", g, "float", 1.6, 0, 20, apply=_setp("linewidth", float), step=0.25))
    add(P(S, "linestyle", "Line style", g, "choice", "-", choices=LINESTYLES, apply=_setp("linestyle", _ls)))
    add(P(S, "drawstyle", "Drawn as", g, "choice", "default", choices=DRAWSTYLES, apply=_setp("drawstyle")))
    add(P(S, "marker", "Marker", g, "choice", "none", choices=MARKERS, apply=_setp("marker", _marker)))
    add(P(S, "markersize", "Marker size", g, "float", 4, 0, 40, apply=_setp("markersize", float), step=0.5))
    add(P(S, "markerfacecolor", "Marker fill", g, "color", "#2b7de9", apply=_setp("markerfacecolor")))
    add(P(S, "markeredgecolor", "Marker edge", g, "color", "#2b7de9", apply=_setp("markeredgecolor")))
    add(P(S, "markeredgewidth", "Marker edge width", g, "float", 1.0, 0, 10, apply=_setp("markeredgewidth", float), step=0.25))
    add(P(S, "fillstyle", "Marker fill style", g, "choice", "full", choices=FILLSTYLES, apply=_setp("fillstyle")))
    add(P(S, "markevery", "Marker on every n-th point", g, "optint", None, 1, 1000, apply=_setp("markevery", int)))
    add(P(S, "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))
    add(P(S, "dash_capstyle", "Dash ends", g, "choice", "butt", choices=CAPS, apply=_setp("dash_capstyle")))
    add(P(S, "dash_joinstyle", "Dash corners", g, "choice", "round", choices=JOINS, apply=_setp("dash_joinstyle")))
    add(P(S, "solid_capstyle", "Line ends", g, "choice", "projecting", choices=CAPS, apply=_setp("solid_capstyle")))
    add(P(S, "solid_joinstyle", "Line corners", g, "choice", "round", choices=JOINS, apply=_setp("solid_joinstyle")))
    add(P(S, "zorder", "Drawing order", g, "float", 2, 0, 20, apply=_setp("zorder", float), step=1))
    add(P(S, "antialiased", "Smooth edges", g, "bool", True, apply=_setp("antialiased")))
    add(P(S, "visible", "Show", g, "bool", True, apply=_setp("visible")))
    add(P(S, "label", "Name in the legend", g, "text", "", apply=_setp("label"), preset=False))

    g = "Bars and areas"
    B = "bars"
    add(P(B, "facecolor", "Fill colour", g, "color", "#2b7de9", apply=_setp("facecolor")))
    add(P(B, "edgecolor", "Edge colour", g, "color", "#1f2a3c", apply=_setp("edgecolor")))
    add(P(B, "linewidth", "Edge width", g, "float", 0.0, 0, 10, apply=_setp("linewidth", float), step=0.25))
    add(P(B, "linestyle", "Edge style", g, "choice", "-", choices=LINESTYLES, apply=_setp("linestyle", _ls)))
    add(P(B, "hatch", "Pattern", g, "choice", "", choices=HATCHES, apply=_setp("hatch", _hatch)))
    add(P(B, "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))
    add(P(B, "joinstyle", "Edge corners", g, "choice", "miter", choices=JOINS, apply=_setp("joinstyle")))
    add(P(B, "capstyle", "Edge ends", g, "choice", "butt", choices=CAPS, apply=_setp("capstyle")))
    add(P(B, "antialiased", "Smooth edges", g, "bool", True, apply=_setp("antialiased")))
    add(P(B, "zorder", "Drawing order", g, "float", 1, 0, 20, apply=_setp("zorder", float), step=1))
    add(P(B, "visible", "Show", g, "bool", True, apply=_setp("visible")))

    g = "Limit lines"
    add(P("limits", "linewidth", "Width", g, "float", 1.2, 0, 10, apply=_setp("linewidth", float), step=0.25))
    add(P("limits", "linestyle", "Line style", g, "choice", "--", choices=LINESTYLES, apply=_setp("linestyle", _ls)))
    add(P("limits", "alpha", "Opacity", g, "float", 1.0, 0, 1, apply=_setp("alpha", float), step=0.05))
    add(P("limits", "zorder", "Drawing order", g, "float", 2, 0, 20, apply=_setp("zorder", float), step=1))

    g = "Shaded zones"
    add(P("zones", "alpha", "Opacity", g, "float", 0.14, 0, 1, apply=_setp("alpha", float), step=0.02))
    add(P("zones", "hatch", "Pattern", g, "choice", "", choices=HATCHES, apply=_setp("hatch", _hatch)))
    add(P("zones", "edgecolor", "Edge colour", g, "color", "#e8590c", apply=_setp("edgecolor")))
    add(P("zones", "linewidth", "Edge width", g, "float", 0.0, 0, 10, apply=_setp("linewidth", float), step=0.25))

    g = "Notes"
    N = "notes"
    add(P(N, "fontsize", "Text size", g, "float", 8.5, 4, 40, apply=_setp("fontsize", float), step=0.5))
    add(P(N, "color", "Text colour", g, "color", "#1f2a3c", apply=_setp("color")))
    add(P(N, "fontweight", "Text weight", g, "choice", "normal", choices=WEIGHTS, apply=_setp("fontweight")))
    add(P(N, "fontstyle", "Text style", g, "choice", "normal", choices=FONTSTYLES, apply=_setp("fontstyle")))
    add(P(N, "rotation", "Text rotation", g, "float", 0, -180, 180, apply=_setp("rotation", float), step=5))
    add(P(N, "arrow_style", "Arrow", g, "choice", "->", choices=ARROWS, apply=_arrow("style")))
    add(P(N, "arrow_color", "Arrow colour", g, "color", "#6a7790", apply=_arrow("color")))
    add(P(N, "arrow_width", "Arrow width", g, "float", 0.9, 0, 10, apply=_arrow("width"), step=0.25))
    add(P(N, "box_style", "Box", g, "choice", "round", choices=BOXES, apply=_box("style")))
    add(P(N, "box_face", "Box fill", g, "color", "#ffffff", apply=_box("face")))
    add(P(N, "box_edge", "Box edge", g, "color", "#c8d0de", apply=_box("edge")))
    return out


def _axis_props(target, title):
    P = Prop
    g = title
    out = []
    add = out.append
    add(P(target, "visible", "Show the axis", g, "bool", True, apply=_axis_visible))
    add(P(target, "scale", "Scale", g, "choice", "linear", choices=SCALES, apply=_axis_scale))
    add(P(target, "inverted", "Reversed", g, "bool", False, apply=_axis_invert))
    add(P(target, "label_size", "Label: size", g, "float", 9, 4, 72, apply=_axis_label("fontsize", float), step=0.5))
    add(P(target, "label_color", "Label: colour", g, "color", "#1f2a3c", apply=_axis_label("color")))
    add(P(target, "label_weight", "Label: weight", g, "choice", "normal", choices=WEIGHTS, apply=_axis_label("fontweight")))
    add(P(target, "label_style", "Label: style", g, "choice", "normal", choices=FONTSTYLES, apply=_axis_label("fontstyle")))
    add(P(target, "label_rotation", "Label: rotation", g, "float", 0, -180, 180, apply=_axis_label("rotation", float), step=5))
    add(P(target, "label_pad", "Label: distance (pt)", g, "float", 4, 0, 60, apply=_axis_labelpad, step=1))
    add(P(target, "tick_dir", "Ticks: direction", g, "choice", "out", choices=TICKDIRS, apply=_tick("major", "direction")))
    add(P(target, "tick_len", "Ticks: length", g, "float", 3.5, 0, 24, apply=_tick("major", "length", float), step=0.5))
    add(P(target, "tick_width", "Ticks: width", g, "float", 0.8, 0, 6, apply=_tick("major", "width", float), step=0.25))
    add(P(target, "tick_color", "Ticks: colour", g, "color", "#6a7790", apply=_tick("major", "color")))
    add(P(target, "tick_pad", "Ticks: distance to the numbers", g, "float", 3.5, 0, 30, apply=_tick("major", "pad", float), step=0.5))
    add(P(target, "ticks_shown", "Ticks: show the marks", g, "bool", True, apply=lambda objs, v: [a.set_tick_params(which="major", **_side(a, bool(v))) for a in objs]))
    add(P(target, "numbers_shown", "Ticks: show the numbers", g, "bool", True, apply=lambda objs, v: [a.set_tick_params(which="major", **_side(a, bool(v), "label")) for a in objs]))
    add(P(target, "numbers_size", "Numbers: size", g, "float", 8, 4, 72, apply=_tick("major", "labelsize", float), step=0.5))
    add(P(target, "numbers_color", "Numbers: colour", g, "color", "#6a7790", apply=_tick("major", "labelcolor")))
    add(P(target, "numbers_rotation", "Numbers: rotation", g, "float", 0, -90, 90, apply=_tick("major", "labelrotation", float), step=5))
    add(P(target, "tick_format", "Numbers: format", g, "choice", "auto", choices=TICKFORMATS, apply=_tick_format))
    add(P(target, "tick_decimals", "Numbers: decimals", g, "optint", None, 0, 10, apply=_tick_decimals))
    add(P(target, "tick_step", "Ticks: a tick every (units)", g, "optfloat", None, 1e-6, 1e12, apply=_tick_step, step=0.001))
    add(P(target, "tick_max", "Ticks: at most this many", g, "optint", None, 2, 60, apply=_tick_max))
    add(P(target, "minor_count", "Minor ticks", g, "choice", "0", choices=MINORS, apply=_minor_count))
    add(P(target, "minor_dir", "Minor ticks: direction", g, "choice", "out", choices=TICKDIRS, apply=_tick("minor", "direction")))
    add(P(target, "minor_len", "Minor ticks: length", g, "float", 2, 0, 24, apply=_tick("minor", "length", float), step=0.5))
    add(P(target, "minor_width", "Minor ticks: width", g, "float", 0.6, 0, 6, apply=_tick("minor", "width", float), step=0.25))
    add(P(target, "minor_color", "Minor ticks: colour", g, "color", "#6a7790", apply=_tick("minor", "color")))
    add(P(target, "grid", "Grid lines", g, "bool", True, apply=_axis_grid("major")))
    add(P(target, "grid_color", "Grid: colour", g, "color", "#e3e8f0", apply=_axis_grid_look("major", "color")))
    add(P(target, "grid_width", "Grid: width", g, "float", 0.8, 0, 6, apply=_axis_grid_look("major", "linewidth", float), step=0.1))
    add(P(target, "grid_style", "Grid: style", g, "choice", "-", choices=LINESTYLES, apply=_axis_grid_look("major", "linestyle", _ls)))
    add(P(target, "grid_alpha", "Grid: opacity", g, "float", 1.0, 0, 1, apply=_axis_grid_look("major", "alpha", float), step=0.05))
    add(P(target, "minor_grid", "Minor grid lines", g, "bool", False, apply=_axis_grid("minor")))
    add(P(target, "minor_grid_color", "Minor grid: colour", g, "color", "#eef1f6", apply=_axis_grid_look("minor", "color")))
    add(P(target, "minor_grid_width", "Minor grid: width", g, "float", 0.5, 0, 6, apply=_axis_grid_look("minor", "linewidth", float), step=0.1))
    add(P(target, "minor_grid_style", "Minor grid: style", g, "choice", ":", choices=LINESTYLES, apply=_axis_grid_look("minor", "linestyle", _ls)))
    add(P(target, "minor_grid_alpha", "Minor grid: opacity", g, "float", 1.0, 0, 1, apply=_axis_grid_look("minor", "alpha", float), step=0.05))
    return out


def _side(axis, on, what=""):
    """The tick_params keywords for the side of `axis` that carries its ticks (bottom for an X axis, left for a Y axis, top / right for the second ones)."""
    ax = axis.axes
    if axis is ax.xaxis:
        top = ax.xaxis.get_ticks_position() in ("top",) or getattr(ax, "_sh_second_x", False)
        return {("label" if what else "") + ("top" if top else "bottom"): on}
    right = ax.yaxis.get_ticks_position() in ("right",) or getattr(ax, "_sh_second_y", False)
    return {("label" if what else "") + ("right" if right else "left"): on}


# ------------------------------------------------------------------------------------------------------------------ matplotlib's own settings
_RC_SKIP_GROUPS = {"keymap", "webagg", "animation", "pdf", "ps", "svg", "pgf", "tk", "macosx", "docstring", "backend", "backend_fallback", "interactive", "toolbar",
                   "timezone", "_internal", "agg", "path", "image", "contour", "pcolor", "pcolormesh", "polaraxes", "axes3d", "boxplot", "hist", "errorbar", "markers",
                   "scatter", "date", "hatch", "xaxis", "yaxis"}
_RC_SKIP_KEYS = {"text.usetex", "text.latex.preamble", "figure.max_open_warning", "figure.raise_window", "figure.hooks", "figure.figsize", "figure.dpi", "figure.autolayout",
                 "figure.constrained_layout.use", "figure.subplot.left", "figure.subplot.right", "figure.subplot.bottom", "figure.subplot.top", "figure.subplot.wspace",
                 "figure.subplot.hspace", "figure.frameon", "figure.titlesize", "figure.titleweight", "figure.labelsize", "figure.labelweight", "savefig.directory",
                 "savefig.format", "axes.prop_cycle", "mathtext.fontset", "mathtext.bf", "mathtext.cal", "mathtext.it", "mathtext.rm", "mathtext.sf", "mathtext.tt",
                 "mathtext.bfit", "mathtext.fallback", "axes.formatter.limits", "axes.formatter.min_exponent", "axes.formatter.offset_threshold", "legend.loc",
                 "figure.constrained_layout.h_pad", "figure.constrained_layout.w_pad", "figure.constrained_layout.hspace", "figure.constrained_layout.wspace",
                 "lines.scale_dashes", "font.family"}
_RC_KEEP_MATH = {"mathtext.default", "mathtext.fontset"}
_FONT_CHOICES = [("sans-serif", "Sans-serif"), ("serif", "Serif"), ("monospace", "Monospace"), ("cursive", "Cursive"), ("fantasy", "Fantasy")]

_RC_CHOICES = {"axes.axisbelow": [("true", "Below everything"), ("line", "Below lines"), ("false", "Above")],
               "font.style": FONTSTYLES, "font.variant": [("normal", "Normal"), ("small-caps", "Small caps")]}
_RC_SKIP_KEYS |= {"lines.marker", "lines.markeredgecolor", "lines.markerfacecolor"}                # (the basic look has the markers)

_rc_cache = None


def _guess_bounds(key, default):
    k = key.lower()
    if "alpha" in k or "fraction" in k or k.endswith("margin"):
        return 0.0, 1.0
    if k.endswith(("numpoints", "scatterpoints")):
        return 1, 10
    if k.endswith(("width", "size", "pad", "length", "spacing", "scale", "radius", "offset")) or "linewidth" in k or "markersize" in k:
        return 0.0, 100.0
    if "dpi" in k:
        return 20.0, 1200.0
    if "rotation" in k:
        return -360.0, 360.0
    if isinstance(default, int):
        return -1000, 1000
    return -1000.0, 1000.0


def _rc_props():
    """matplotlib's own settings that change how a chart looks, read from the installed matplotlib: a Prop for each (key "rc:<name>")."""
    global _rc_cache
    if _rc_cache is not None:
        return _rc_cache
    out = []
    try:
        import matplotlib as mpl
        from matplotlib import rcsetup
        defaults = mpl.rcParamsDefault
        validators = rcsetup._validators
    except Exception:                                     # noqa: BLE001 - no matplotlib: no list
        _rc_cache = out
        return out
    for key in sorted(defaults):
        group = key.split(".")[0]
        if key in _RC_SKIP_KEYS and key not in _RC_KEEP_MATH:
            continue
        if group in _RC_SKIP_GROUPS or (group == "mathtext" and key not in _RC_KEEP_MATH):
            continue
        v = validators.get(key)
        if v is None:
            continue
        default = defaults[key]
        gtitle = {"axes": "Defaults: axes", "lines": "Defaults: lines", "patch": "Defaults: patches (bars, areas)", "font": "Defaults: font", "text": "Defaults: text",
                  "xtick": "Defaults: X ticks", "ytick": "Defaults: Y ticks", "grid": "Defaults: grid", "legend": "Defaults: legend", "figure": "Defaults: figure",
                  "savefig": "Defaults: saving", "mathtext": "Defaults: maths text"}.get(group, f"Defaults: {group}")
        kind, lo, hi, choices = None, None, None, None
        name = getattr(v, "__name__", type(v).__name__)
        valid = getattr(v, "valid", None)
        if key in _RC_CHOICES:
            kind, choices = "choice", list(_RC_CHOICES[key])
            default = str(default).lower() if isinstance(default, bool) else str(default)
        elif isinstance(valid, dict):
            vals = []
            for x in valid.values():
                if x not in vals and x is not None and x != "":
                    vals.append(x)
            kind, choices = "choice", [(str(x), str(x)) for x in vals]
        elif name in ("CapStyle", "JoinStyle") or type(default).__name__ in ("CapStyle", "JoinStyle"):
            kind = "choice"
            choices = CAPS if "cap" in key else JOINS
            default = str(getattr(default, "value", default))
        elif "linestyle" in name:
            kind, choices = "choice", [("solid", "Solid"), ("dashed", "Dashed"), ("dashdot", "Dash-dot"), ("dotted", "Dotted")]
            default = {"-": "solid", "--": "dashed", "-.": "dashdot", ":": "dotted"}.get(default, default)
        elif "fontsize" in name:
            kind = "fontsize"
        elif "fontweight" in name:
            kind, choices = "choice", WEIGHTS + [("ultralight", "Ultra light"), ("medium", "Medium"), ("bold", "Bold")]
        elif "fontstretch" in name:
            kind, choices = "choice", [(x, x) for x in ("ultra-condensed", "extra-condensed", "condensed", "semi-condensed", "normal", "semi-expanded", "expanded",
                                                        "extra-expanded", "ultra-expanded")]
        elif isinstance(default, bool):
            kind = "bool"
        elif "color" in name or key.endswith("color"):
            kind = "color"
        elif isinstance(default, int):
            kind = "int"
            lo, hi = _guess_bounds(key, default)
            lo, hi = int(lo), int(hi)
        elif isinstance(default, float):
            kind = "float"
            lo, hi = _guess_bounds(key, default)
        elif isinstance(default, str):
            kind = "text"
        elif isinstance(default, (list, tuple)):
            kind = "text"
        else:
            continue
        if kind == "choice" and (not choices or default is None):
            continue
        if kind == "choice" and str(default) not in {c[0] for c in choices}:
            choices = list(choices) + [(str(default), str(default))]
        p = Prop("rc", key, key, gtitle, kind, default, lo, hi, choices, preset=True, step=(0.1 if kind == "float" else None))
        out.append(p)
    _rc_cache = out
    return out


# ------------------------------------------------------------------------------------------------------------------ the table
_props = None
_by_key = None


def props():
    """Every property: the object properties first, then matplotlib's own settings."""
    global _props, _by_key
    if _props is None:
        _props = _object_props() + _rc_props()
        _by_key = {p.key: p for p in _props}
    return _props


def get(key):
    """The Prop for a stored key (an index in "series[2]:name" is ignored); None when it is not known."""
    props()
    t, _i, n = split_key(key)
    return _by_key.get(f"{t}:{n}")


_KEY = re.compile(r"^([a-z0-9_]+)(?:\[(\d+)\])?:(.+)$")


def split_key(key):
    """'series[2]:linewidth' -> ('series', 2, 'linewidth'); 'rc:axes.grid' -> ('rc', None, 'axes.grid').  Bad text -> ('', None, '')."""
    m = _KEY.match(key or "")
    if not m:
        return "", None, ""
    return m.group(1), (int(m.group(2)) if m.group(2) is not None else None), m.group(3)


def make_key(target, name, index=None):
    return f"{target}[{index}]:{name}" if index is not None else f"{target}:{name}"


INDEXED = ("series", "bars")                               # targets that can be set for one series only


def groups():
    """[(group title, [Prop, ...])] in display order."""
    seen, out = {}, []
    for p in props():
        if p.group not in seen:
            seen[p.group] = []
            out.append((p.group, seen[p.group]))
        seen[p.group].append(p)
    return out


# ------------------------------------------------------------------------------------------------------------------ checking a typed value
def _color_ok(v):
    try:
        from matplotlib.colors import is_color_like
        return isinstance(v, str) and is_color_like(v)
    except Exception:                                     # noqa: BLE001
        return False


def to_hex(v):
    """A colour as '#rrggbb' (or '#rrggbbaa' when it has transparency); the text itself when matplotlib does not know it."""
    try:
        from matplotlib.colors import to_hex as _hex, to_rgba
        return _hex(v, keep_alpha=to_rgba(v)[3] < 1.0)
    except Exception:                                     # noqa: BLE001
        return str(v)


NAMED_SIZES = ("xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large")


def coerce(p, raw):
    """(ok, value, message) for a value typed or picked for property `p`.  value None (ok True) means "unset" for the optional kinds."""
    k = p.kind
    try:
        if k == "bool":
            if isinstance(raw, str):
                return True, raw.strip().lower() in ("1", "true", "yes", "on"), ""
            return True, bool(raw), ""
        if k in ("int", "float", "optint", "optfloat"):
            if raw is None or (isinstance(raw, str) and raw.strip() == ""):
                if k.startswith("opt"):
                    return True, None, ""
                return False, None, f"{p.label}: a number is needed."
            x = float(raw)
            if x != x or x in (float("inf"), float("-inf")):
                return False, None, f"{p.label}: not a number."
            lo = p.lo if p.lo is not None else -1e12
            hi = p.hi if p.hi is not None else 1e12
            x = max(lo, min(hi, x))
            return True, (int(round(x)) if k in ("int", "optint") else x), ""
        if k == "fontsize":
            if isinstance(raw, str) and raw in NAMED_SIZES:
                return True, raw, ""
            x = float(raw)
            return True, max(4.0, min(72.0, x)), ""
        if k == "color":
            if _color_ok(raw):
                return True, to_hex(raw) if str(raw).startswith("#") else raw, ""
            return False, None, f"{p.label}: '{raw}' is not a colour."
        if k == "choice":
            keys = [c[0] for c in (p.choices or [])]
            if raw in keys:
                return True, raw, ""
            if str(raw) in keys:
                return True, str(raw), ""
            return False, None, f"{p.label}: choose one from the list."
        if k == "text":
            t = "" if raw is None else str(raw)
            if len(t) > 200:
                t = t[:200]
            if p.target == "rc":                                  # matplotlib's own check, so a value it would refuse is told at once
                import matplotlib as mpl
                try:
                    mpl.rcParams.validate[p.name](_rc_value(p, t))
                except (ValueError, KeyError, TypeError) as ex:
                    return False, None, f"{p.label}: {str(ex).splitlines()[0][:80]}"
            return True, t, ""
    except (TypeError, ValueError):
        return False, None, f"{p.label}: '{raw}' is not valid."
    return False, None, f"{p.label}: unknown kind."


def _rc_value(p, raw):
    """The Python value that matplotlib's validator takes for the stored value (text for lists is split at the commas)."""
    default = p.default
    if p.kind == "text" and isinstance(default, (list, tuple)):
        parts = [x.strip() for x in str(raw).split(",") if x.strip()]
        if default and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in default):
            parts = [float(x) for x in parts]
            if all(isinstance(x, int) for x in default):
                parts = [int(x) for x in parts]
        return parts
    if p.kind == "choice" and p.name.endswith(("capstyle", "joinstyle")):
        return raw
    if p.kind == "choice" and p.name.endswith("linestyle"):
        return raw
    return raw


def rc_values(adv):
    """({matplotlib key: value} for the "rc:" entries of `adv` that matplotlib accepts, [notes about the others])."""
    out, notes = {}, []
    props()
    try:
        import matplotlib as mpl
        validate = mpl.rcParams.validate
    except Exception:                                     # noqa: BLE001
        return out, notes
    for key, raw in (adv or {}).items():
        t, _i, name = split_key(key)
        if t != "rc":
            continue
        p = _by_key.get(key)
        if p is None:
            notes.append(f"{name}: this matplotlib has no such setting.")
            continue
        ok, val, msg = coerce(p, raw) if p.kind != "text" else (True, raw, "")
        if not ok:
            notes.append(msg)
            continue
        try:
            out[name] = validate[name](_rc_value(p, val))
        except (ValueError, KeyError, TypeError) as ex:
            notes.append(f"{name}: {str(ex).splitlines()[0][:90]}")
    return out, notes


# ------------------------------------------------------------------------------------------------------------------ applying to what the chart drew
def apply_objects(adv, targets, notes, only=None, skip=()):
    """Sets each stored object property.  `targets` maps a target name to the list of objects it means (for "series" and "bars": one entry per series, None where a
    series has none); `only` / `skip` choose targets by name.  A property that cannot be set adds a note and the rest go on."""
    props()
    for key, raw in (adv or {}).items():
        t, index, name = split_key(key)
        if t in ("", "rc") or (only is not None and t not in only) or t in skip:
            continue
        p = _by_key.get(f"{t}:{name}")
        if p is None or p.apply is None:
            continue
        objs = targets.get(t)
        if not objs:
            continue
        if t in INDEXED:
            objs = [objs[index]] if index is not None and 0 <= index < len(objs) else ([] if index is not None else list(objs))
        objs = [o for o in objs if o is not None]
        if not objs:
            continue
        ok, val, msg = coerce(p, raw)
        if not ok:
            notes.append(msg)
            continue
        if val is None:
            continue
        try:
            p.apply(objs, val)
        except Exception as ex:                          # noqa: BLE001 - matplotlib refused it: say which one and go on
            notes.append(f"{p.group} - {p.label}: {str(ex).splitlines()[0][:90] if str(ex) else type(ex).__name__}")
