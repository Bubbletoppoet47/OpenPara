"""
icon_kit.py - the icon look of OpenPara: "2000 bevel".  Flat blue-grey bodies with a raised 1 px edge, a navy outline and a muted accent colour.

Every icon is one small drawing on a 24 x 24 grid (icon_shapes.py, icon_set.py and the add-ons hold them); this file dresses it.  The drawing's
elements carry a role in their class:   b body   p paper (white)   a accent shape   l ink line   n accent line   d dot   k solid ink   th pipe.
The palette is in LOOK and HUES below, in one place: change a colour there and every icon follows.

    register({key: (svg elements, hue)})      add drawings (an add-on registers its own)
    has(key)                                  True when a drawing of that name exists
    pixmap(key, size, ratio=2, enabled=True) -> QPixmap   the icon, drawn crisp at size x ratio device pixels (enabled=False: greyed)
    qicon(key, size=40) -> QIcon              the same as a QIcon (several sizes, cached)

The bevel is made from the picture itself (a mask shifted by one device pixel), because Qt's SVG renderer does not do clip paths.
"""
import re

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

# ---- the look (change colours here)
LOOK = {
    "ink": "#10204d",        # the outline and the lines: the navy of the logo
    "body": "#cbd3e0",       # flat body: a cool blue-grey, close to the greys of the window
    "paper": "#ffffff",
    "hi": "#ffffff",         # raised edge, top and left
    "lo": "#7a869c",         # raised edge, bottom and right
    "grey": "#808a9c",       # what an accent colour is toned toward
    "mute": 0.20,            # how much of that grey goes into an accent colour ...
    "mute_blue": 0.10,       # ... and into blue, the main accent
    "line": 1.0,             # line width, in grid units (never under one device pixel)
    "crisp": True,           # hard edges, like the old toolbars
}
HUES = {"feat": "#2f6fed", "cut": "#d6453d", "ref": "#c27a00", "asm": "#0e9488", "ana": "#7c4dcc", "cfg": "#5f6b7a", "ai": "#b83280", "dat": "#2e8b57"}

_ELEM = re.compile(r'<(path|circle|ellipse|rect) class="(\w+)"([^>]*?)\s*/>')
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"')
_SHAPES = {}
_loaded = False
_cache = {}
_icons = {}


def register(shapes):
    """Add drawings: {key: (svg elements, hue)}.  A key that already holds another drawing is an error."""
    for k, v in shapes.items():
        if k in _SHAPES and _SHAPES[k] != v:
            raise ValueError(f"icon '{k}' is already drawn")
        _SHAPES[k] = v


def _ensure():
    global _loaded
    if not _loaded:
        _loaded = True
        import icon_set          # the tree / tab drawings
        import icon_shapes       # the rest of the program's drawings
        register(icon_shapes.CORE)
        icon_set.register_shapes()


def has(key):
    _ensure()
    return key in _SHAPES


def keys():
    _ensure()
    return list(_SHAPES)


# ---- colours
def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _mix(a, b, t):
    A, B = _rgb(a), _rgb(b)
    return "#" + "".join(f"{max(0, min(255, round(x * (1 - t) + y * t))):02x}" for x, y in zip(A, B))


def _tone(hue_key):
    h = HUES.get(hue_key, HUES["cfg"])
    k = LOOK["mute_blue"] if hue_key == "feat" else LOOK["mute"]
    base = _mix(h, LOOK["grey"], k)
    return {"acc": _mix(base, "#000000", .08), "line": _mix(_mix(h, LOOK["grey"], k * .75), "#000000", .15),
            "dot": _mix(_mix(h, LOOK["grey"], k * .75), "#000000", .05), "tube": _mix(base, "#ffffff", .5)}


# ---- drawing
def _svg(tag, geo, **more):
    a = dict(geo)
    a.update({k.replace("_", "-"): v for k, v in more.items() if v is not None})
    cap, join = ("butt", "miter")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-linecap="{cap}" stroke-linejoin="{join}">'
            f'<{tag} ' + " ".join(f'{k}="{v}"' for k, v in a.items()) + "/></svg>").encode()


def _render(p, tag, geo, W, **more):
    r = QSvgRenderer(QByteArray(_svg(tag, geo, **more)))
    r.render(p, QRectF(0, 0, W, W))


def _painter(img, crisp):
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, not crisp)
    return p


def _mask(tag, geo, W, crisp):
    m = QImage(W, W, QImage.Format.Format_ARGB32_Premultiplied)
    m.fill(Qt.GlobalColor.transparent)
    p = _painter(m, crisp)
    _render(p, tag, geo, W, fill="#000000", stroke="none")
    p.end()
    return m


def _band(mask, dx, dy, color):
    """The pixels of the mask whose neighbour at (-dx, -dy) is outside it, in one colour: one raised edge."""
    out = QImage(mask)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
    p.drawImage(dx, dy, mask)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


def image(key, size, ratio=2):
    """The icon as a QImage of size x ratio pixels."""
    _ensure()
    ck = (key, size, ratio)
    if ck in _cache:
        return _cache[ck]
    inner, hue = _SHAPES[key]
    W = max(8, int(round(size * ratio)))
    u = W / 24.0                                         # device pixels per grid unit
    crisp = bool(LOOK["crisp"])
    t = _tone(hue)
    ink = LOOK["ink"]
    ow = max(int(ratio), round(u * LOOK["line"]))        # outline width in device pixels (never under one logical pixel)
    sw = ow / u                                          # ... and in grid units
    kw = sw / 1.5                                        # the drawings state widths for a 1.5 line
    d = max(1, round(u * 0.5))                           # raised edge
    shift = d + (ow + 1) // 2
    img = QImage(W, W, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = _painter(img, crisp)
    for m in _ELEM.finditer(inner):
        tag, role, rest = m.group(1), m.group(2), m.group(3)
        own = dict(_ATTR.findall(rest))
        style = own.pop("style", "")
        if "display:none" in style.replace(" ", ""):
            continue
        op = re.search(r"(?<![-\w])opacity:\s*([\d.]+)", style)
        opacity = float(op.group(1)) if op else 1.0
        nostroke = "stroke:none" in style.replace(" ", "")
        widths = own.pop("stroke-width", None)
        geo = {k: v for k, v in own.items() if k not in ("fill", "stroke")}
        lw = (float(widths) * kw if widths else sw)
        lw = max(lw, 1.0 / u)
        p.setOpacity(opacity)
        if role in ("b", "p", "a"):
            fill = {"b": LOOK["body"], "p": LOOK["paper"], "a": t["acc"]}[role]
            mask = _mask(tag, geo, W, crisp)
            flat = QImage(mask)
            q = QPainter(flat)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            q.fillRect(flat.rect(), QColor(fill))
            q.end()
            p.drawImage(0, 0, flat)
            if not nostroke:
                p.drawImage(0, 0, _band(mask, -shift, -shift, LOOK["lo"]))
                p.drawImage(0, 0, _band(mask, shift, shift, LOOK["hi"]))
                _render(p, tag, geo, W, fill="none", stroke=ink, stroke_width=f"{lw:.3f}")
        elif role == "l":
            _render(p, tag, geo, W, fill="none", stroke=ink, stroke_width=f"{lw:.3f}")
        elif role == "n":
            _render(p, tag, geo, W, fill="none", stroke=t["line"], stroke_width=f"{lw:.3f}")
        elif role == "d":
            _render(p, tag, geo, W, fill=t["dot"], stroke=ink, stroke_width=f"{max(0.7 * sw, 1.0 / u):.3f}")
        elif role == "k":
            _render(p, tag, geo, W, fill=ink, stroke="none")
        elif role == "th":
            _render(p, tag, geo, W, fill="none", stroke=ink, stroke_width=f"{5.6 * kw * 1.1:.3f}")
            _render(p, tag, geo, W, fill="none", stroke=t["tube"], stroke_width=f"{4.2 * kw * 1.1:.3f}")
    p.end()
    _cache[ck] = img
    return img


def _dim(img):
    """The grey, half-faded version of an icon (for a button that is switched off)."""
    g = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(g)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(0, 0, img)
    p.end()
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(0.45)
    p.drawImage(0, 0, g)
    p.end()
    return out


def pixmap(key, size, ratio=2, enabled=True):
    """The icon as a QPixmap (size x ratio device pixels, device pixel ratio set); enabled=False gives the greyed one."""
    img = image(key, size, ratio)
    if not enabled:
        ck = (key, size, ratio, "off")
        if ck not in _cache:
            _cache[ck] = _dim(img)
        img = _cache[ck]
    px = QPixmap.fromImage(img)
    px.setDevicePixelRatio(ratio)
    return px


def qicon(key, size=40):
    """The QIcon of a drawing (None when there is none): sharp at the sizes the program uses (16 tree, 20 to 24 panel buttons, 26 tabs, 36 and 40 ribbon)."""
    if not has(key):
        return None
    k = (key, size)
    if k not in _icons:
        ic = QIcon()
        for s in sorted({size, 16, 20, 22, 24, 26, 32, 36, 40}):
            ic.addPixmap(pixmap(key, s, 1))                      # a 1x screen gets exact pixels,
            ic.addPixmap(pixmap(key, s, 2))                      # a 2x screen gets twice as many
        _icons[k] = ic
    return _icons[k]
