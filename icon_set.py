"""
icon_set.py - the picked icon set: one style for the ribbon, the part tree and the assembly tree.

Each icon is a small SVG on a 24 x 24 grid.  The shapes carry a class (b body, a accent, l line, n accent line, d dot, th pipe) that is turned into plain
attributes here (the soft tint is a fill opacity), so Qt's SVG renderer needs no stylesheet.  Colour says what the thing is: blue = features that add
material, red = cuts, amber = reference geometry, teal = assembly structure, purple = simulation and render, grey = configurations.

qicon(key, size) -> QIcon;  by_label(button text) -> QIcon or None;  decorate_tree(tree, root_key) puts icons on tree rows that start with a glyph.
"""
import re

from PyQt6.QtCore import QByteArray, QRectF, Qt, QSize
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

INK = "#26303c"
HUE = {"feat": "#2f6fed", "cut": "#d6453d", "ref": "#c27a00", "asm": "#0e9488", "ana": "#7c4dcc", "cfg": "#5f6b7a"}

PICKS = {
    'assembly': ('<path class="b" d="M12 3l9 4.5-9 4.5-9-4.5z"/><path class="l" d="M3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>', 'asm'),
    'component': ('<path class="b" d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path class="l" d="M4 7.5l8 4.5 8-4.5M12 12v9"/>', 'asm'),
    'subassembly': ('<rect class="b" x="8.5" y="2.5" width="7" height="6" rx="1"/><rect class="a" x="2.5" y="15.5" width="7" height="6" rx="1"/><rect class="a" x="14.5" y="15.5" width="7" height="6" rx="1"/><path class="l" d="M12 8.5v3.5M6 15.5V12h12v3.5"/>', 'asm'),
    'plane': ('<path class="b" d="M7 5h13l-3 14H4z"/>', 'ref'),
    'origin': ('<path class="l" d="M5 19V4.5M5 19h14.5M5 4.5L3.5 7M5 4.5L6.5 7M19.5 19L17 17.5M19.5 19L17 20.5"/><circle class="a" cx="5" cy="19" r="2.2"/>', 'ref'),
    'refpoint': ('<circle class="a" cx="12" cy="12" r="3.2"/><path class="l" d="M12 3v4M12 17v4M3 12h4M17 12h4"/>', 'ref'),
    'refaxis': ('<path class="l" stroke-dasharray="3 2" d="M4 20L20 4"/><circle class="a" cx="4" cy="20" r="1.8"/><circle class="a" cx="20" cy="4" r="1.8"/>', 'ref'),
    'refgeo': ('<path class="l" stroke-dasharray="3 2" d="M4 6h16v12H4z"/><path class="n" d="M2.5 21.5l19-19"/>', 'ref'),
    'pattern': ('<rect class="b" x="2.5" y="8" width="5" height="8" rx="1"/><rect class="b" x="9.5" y="8" width="5" height="8" rx="1" style="opacity:.7"/><rect class="b" x="16.5" y="8" width="5" height="8" rx="1" style="opacity:.4"/>', 'feat'),
    'simulation': ('<path class="n" d="M2 12c2-8 4-8 6 0s4 8 6 0 4-8 6 0"/>', 'ana'),
    'render': ('<rect class="b" x="2.5" y="6.5" width="19" height="13" rx="2"/><circle class="a" cx="12" cy="13" r="3.6"/><path class="l" d="M8 6.5L9.2 4h5.6L16 6.5"/>', 'ana'),
    'mate': ('<rect class="b" x="2.5" y="8" width="12" height="8" rx="4"/><rect class="a" x="9.5" y="8" width="12" height="8" rx="4"/>', 'asm'),
    'config': ('<circle class="a" cx="5" cy="12" r="2.4"/><circle class="b" cx="19" cy="5.5" r="2.4"/><circle class="b" cx="19" cy="18.5" r="2.4"/><path class="l" d="M7.4 12h3c3 0 3-6.5 6.2-6.5M10.4 12c3 0 3 6.5 6.2 6.5"/>', 'cfg'),
    'boss_extrude': ('<path class="b" d="M9.8 3.8L20.2 3.8L20.2 14.2L9.8 14.2z"/><path class="l" d="M4 9.6L9.8 3.8"/><path class="l" d="M14.4 9.6L20.2 3.8"/><path class="l" d="M14.4 20L20.2 14.2"/><path class="l" d="M4 20L9.8 14.2"/><path class="a" d="M4 9.6L14.4 9.6L14.4 20L4 20z"/>', 'feat'),
    'boss_revolve': ('<path class="b" d="M7.5 4L5.3 4.27L3.25 5.07L1.49 6.34L0.14 8L-0.71 9.93L-1 12L-0.71 14.07L0.14 16L1.49 17.66L3.25 18.93L5.3 19.73L7.5 20z" style="opacity:.35"/><path class="b" d="M7.5 4L9.7 4.27L11.75 5.07L13.51 6.34L14.86 8L15.71 9.93L16 12L15.71 14.07L14.86 16L13.51 17.66L11.75 18.93L9.7 19.73L7.5 20z"/><path class="n" d="M7.5 1.5v21" stroke-dasharray="3 1.6"/><path class="l" d="M17.5 3.2a9 3 0 0 0-20 0" style="opacity:.0"/>', 'feat'),
    'boss_sweep': ('<path class="th" d="M6 20C19 20 20 12 12 12C4 12 5 4 19 4"/><path class="l" d="M6 20C19 20 20 12 12 12C4 12 5 4 19 4"/><circle class="a" cx="6" cy="20" r="2.7"/>', 'feat'),
    'boss_loft': ('<path class="b" d="M8 6.5L16 6.5L21 17L3 17z" style="stroke:none"/><path class="l" d="M8 6.5L3 17"/><path class="l" d="M16 6.5L21 17"/><ellipse class="b" cx="12" cy="17" rx="9" ry="4.5"/><ellipse class="a" cx="12" cy="6.5" rx="4" ry="2"/>', 'feat'),
    'cut_extrude': ('<path class="b" d="M9 3L21 3L21 15L9 15z"/><path class="l" d="M3.4 8.6L9 3"/><path class="l" d="M15.4 8.6L21 3"/><path class="l" d="M15.4 20.6L21 15"/><path class="l" d="M3.4 20.6L9 15"/><path class="b" d="M3.4 8.6L15.4 8.6L15.4 20.6L3.4 20.6z"/><circle class="a" cx="9.4" cy="14.6" r="2.8"/>', 'cut'),
    'cut_revolve': ('<rect class="b" x="4" y="4" width="16" height="16" rx="0.8"/><path class="a" d="M4 8.6a3.4 3.4 0 0 1 0 6.8z"/><path class="a" d="M20 15.4a3.4 3.4 0 0 1 0-6.8z"/><path class="n" stroke-dasharray="3 1.6" d="M12 1.5v21"/>', 'cut'),
    'cut_sweep': ('<path class="b" d="M2.5 2.5L21.5 2.5L21.5 21.5L2.5 21.5z"/><path class="th" d="M6 20C19 20 20 12 12 12C4 12 5 4 19 4"/><path class="l" d="M6 20C19 20 20 12 12 12C4 12 5 4 19 4"/><circle class="a" cx="6" cy="20" r="2.7"/>', 'cut'),
    'cut_loft': ('<path class="b" d="M2.5 3L21.5 3L21.5 21.5L2.5 21.5z"/><path class="b" d="M8 6.5L16 6.5L21 17L3 17z" style="stroke:none"/><path class="l" d="M8 6.5L3 17"/><path class="l" d="M16 6.5L21 17"/><ellipse class="b" cx="12" cy="17" rx="9" ry="4.5"/><ellipse class="a" cx="12" cy="6.5" rx="4" ry="2"/>', 'cut'),
    'tb_refgeo': ('<path class="b" d="M2.5 17L7 10.5L21.5 10.5L17 17z"/><path class="l" d="M11.83 10.5L7.33 17" style="opacity:.45"/><path class="l" d="M16.67 10.5L12.17 17" style="opacity:.45"/><path class="l" d="M4.75 13.75L19.25 13.75" style="opacity:.45"/><path class="n" d="M12 2.5v17M9.4 5.2L12 2.5l2.6 2.7"/><circle class="a" cx="12" cy="13.75" r="1.6"/>', 'ref'),
    'sketch': ('<path class="n" d="M3.5 19.5c2-6 5-8 8-5.5s5.500-4 8.500-8"/><path class="a" d="M15 3.8l5.200 5.200-7.700 7.700-5.800.6.600-5.800z" style="display:none"/><circle class="a" cx="3.5" cy="19.5" r="1.6"/><circle class="a" cx="20.5" cy="6.5" r="1.6"/>', 'feat'),
    'fillet': ('<path class="b" d="M3 4h12a6 6 0 0 1 6 6v10H3z"/><path class="n" d="M15 4a6 6 0 0 1 6 6"/>', 'feat'),
    'chamfer': ('<path class="b" d="M3 4h12l6 6v10H3z"/><path class="n" d="M15 4l6 6"/>', 'feat'),
    'mirror': ('<path class="a" d="M3 5l7 7-7 7z"/><path class="b" d="M21 5l-7 7 7 7z"/><path class="n" stroke-dasharray="2 2" d="M12 2.5v19"/>', 'feat'),
    'partgen': ('<path class="b" d="M21.02 10.21L21.02 13.79L17.74 15.83L15.83 17.74L13.79 21.02L10.21 21.02L8.17 17.74L6.26 15.83L2.98 13.79L2.98 10.21L6.26 8.17L8.17 6.26L10.21 2.98L13.79 2.98L15.83 6.26L17.74 8.17z"/><circle class="a" cx="12" cy="12" r="2.6"/>', 'feat'),
    'imported': ('<path class="b" d="M4 12.5h16v8H4z"/><path class="n" d="M12 3v9M8.500 8.500L12 12l3.500-3.500"/>', 'feat'),
    'refplane': ('<path class="b" d="M7 5h13l-3 14H4z"/>', 'ref'),
    'equations': ('<rect class="b" x="3.5" y="3.5" width="17" height="17" rx="3"/><path class="n" d="M16.5 7.5h-8l3.5 4.5-3.5 4.5h8"/>', 'cfg'),
    'material': ('<rect class="b" x="3.5" y="3.5" width="17" height="17" rx="3"/><path class="n" d="M3.5 14.500l11-11M3.5 20.500l17-17M9.500 20.500l11-11"/>', 'cfg'),
}

# toolbar button text (lower case, line breaks as spaces) -> icon key
LABELS = {
    "extruded boss/base": "boss_extrude", "revolved boss/base": "boss_revolve", "swept boss/base": "boss_sweep", "lofted boss/base": "boss_loft",
    "extruded cut": "cut_extrude", "revolved cut": "cut_revolve", "swept cut": "cut_sweep", "lofted cut": "cut_loft",
    "reference geometry": "tb_refgeo", "fillet": "fillet", "chamfer": "chamfer", "mirror": "mirror", "part generator": "partgen",
    "linear pattern": "pattern", "linear component pattern": "pattern", "mirror components": "mirror", "mate": "mate",
}
# part features (the "kind" of a feature) -> icon key
FEATURE = {"sketch": "sketch", "extrude": "boss_extrude", "cut": "cut_extrude", "fillet": "fillet", "chamfer": "chamfer", "revolve": "boss_revolve",
           "revolve_cut": "cut_revolve", "partgen": "partgen", "imported": "imported", "sweep": "boss_sweep", "sweep_cut": "cut_sweep", "loft": "boss_loft",
           "loft_cut": "cut_loft", "pattern": "pattern", "mirror": "mirror", "refplane": "refplane", "refaxis": "refaxis", "refpoint": "refpoint"}
# the glyph a tree row used to start with -> icon key
GLYPH = {"▯": "plane", "⊹": "origin", "∿": "simulation", "◉": "render", "▣": "component", "▱": "refplane", "⁞": "refaxis", "·": "refpoint", "☷": "pattern", "⚯": "mate", "∑": "equations", "◈": "material"}

_ATTR = {
    "b": 'fill="{h}" fill-opacity="0.22" stroke="{i}"',
    "a": 'fill="{h}" stroke="{h}"',
    "l": 'fill="none" stroke="{i}"',
    "n": 'fill="none" stroke="{h}"',
    "d": 'fill="{h}" stroke="none"',
    "th": 'fill="none" stroke="{h}" stroke-width="5.5" opacity="0.28"',
}
_cache = {}


def svg_text(key):
    inner, role = PICKS[key]
    h = HUE[role]

    def sub(m):
        return f"<{m.group(1)} " + _ATTR[m.group(2)].format(h=h, i=INK) + m.group(3)

    inner = re.sub(r'<(path|circle|ellipse|rect) class="(\w+)"([^>]*)', sub, inner)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>")


def pixmap(key, size, ratio=2):
    r = QSvgRenderer(QByteArray(svg_text(key).encode("utf-8")))
    px = QPixmap(size * ratio, size * ratio)
    px.fill(Qt.GlobalColor.transparent)
    g = QPainter(px)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    pad = size * ratio * 0.04
    r.render(g, QRectF(pad, pad, size * ratio - 2 * pad, size * ratio - 2 * pad))
    g.end()
    px.setDevicePixelRatio(ratio)
    return px


def qicon(key, size=40):
    if key not in PICKS:
        return None
    k = (key, size)
    if k not in _cache:
        ic = QIcon()
        for s in sorted({size, 16, 24, 32, 40}):
            ic.addPixmap(pixmap(key, s))
        _cache[k] = ic
    return _cache[k]


def by_label(name, size=40):
    key = LABELS.get(name.lower().replace("\n", " "))
    return qicon(key, size) if key else None


def for_feature(kind):
    return qicon(FEATURE.get(kind, ""), 16)


def decorate_tree(tree, root_key="assembly"):
    """Take the old text glyph off the start of every row and give the row its icon instead; sets a 16 px icon size."""
    tree.setIconSize(QSize(16, 16))

    def walk(it, top):
        t = it.text(0)
        key = None
        if t[:1] == "⬢" and t[1:3] == "  ":
            key = root_key
        elif t[:1] in GLYPH and t[1:3] == "  ":
            key = GLYPH[t[0]]
            if t[0] == "▱" and t.startswith("▱  Reference Geometry"):
                key = "refgeo"
        if key is not None:
            it.setText(0, t[3:])
            it.setIcon(0, qicon(key, 16))
        for i in range(it.childCount()):
            walk(it.child(i), False)

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i), True)
