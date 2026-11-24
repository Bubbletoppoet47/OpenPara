"""
sim_tags.py - the lettered colour tags of the conditions (supports, loads, thermal conditions) of an FEA window, as ANSYS Mechanical has them.

Every condition gets a letter (A, B, C ... in the order of the conditions table: supports first, then loads) and a colour that follows its kind.  The same tag is in three places:
    the row of the condition under its node in the Outline (a coloured square with the letter),
    the list in the upper-left corner of the view (a coloured chip with the letter, then the name),
    a chip at the condition itself on the model.
A tag is a dict:  {"letter", "name", "type", "where", "value", "group", "kind", "colour", "item", "row", "anchor"}   (anchor: where the condition sits in the model's own
coordinates (x, y) or (x, y, z), or None).  There is no title, no date and no explaining text anywhere.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen

KIND_COLOURS = {"support": "#2f6fdc", "slide": "#e0b000", "bearing": "#7a4dc2", "contact": "#7a4dc2", "force": "#d12f2f", "pressure": "#e8742a", "point": "#a61e4d",
                "gravity": "#1f7a2c", "moment": "#a61e4d", "temperature": "#d12f2f", "flux": "#e8742a", "power": "#a61e4d", "convection": "#1f7a2c", "radiation": "#7a4dc2",
                "insulated": "#5b6770", "size": "#0e7f86", "load": "#d12f2f"}
# what the Type text of a condition says -> its kind (the first word that matches wins)
WORDS = (("fixed", "support"), ("pinned", "support"), ("insulat", "insulated"), ("convect", "convection"), ("radiat", "radiation"), ("heat flux", "flux"), ("flux", "flux"), ("heat flow", "power"), ("heat gen", "power"),
         ("temperature", "temperature"), ("gravity", "gravity"), ("pressure", "pressure"), ("moment", "moment"), ("vertex", "point"), ("force", "force"), ("wind", "pressure"),
         ("snow", "pressure"), ("line load", "force"), ("bearing", "bearing"), ("contact", "contact"), ("bolt", "bearing"), ("screw", "bearing"), ("one direction", "slide"),
         ("ux = 0", "slide"), ("uy = 0", "slide"), ("slide", "slide"))


def letter(i):
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    s = ""
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def kind_of(group, type_text):
    t = (type_text or "").lower()
    for word, kind in WORDS:
        if word in t:
            return kind
    return "support" if (group or "").lower() == "supports" else "load"


def colour_of(kind):
    return KIND_COLOURS.get(kind, "#8b95a8")


# ------------------------------------------------------------------------------------------------------------------------------ 2D drawing
CHIP_H = 17
CHIP_FONT_PX = 11


def _font(bold=True, px=CHIP_FONT_PX):
    f = QFont()
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def chip_width(text):
    return max(CHIP_H, QFontMetricsF(_font()).horizontalAdvance(text) + 10)


def paint_chip(p, x, y, text, colour, outline=True):
    """A rounded coloured chip with a white letter, its top-left corner at (x, y).  -> its rectangle."""
    w = chip_width(text)
    r = QRectF(x, y, w, CHIP_H)
    p.save()
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor("white"), 1.4) if outline else Qt.PenStyle.NoPen)
        p.setBrush(QColor(colour))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("white"))
        p.setFont(_font())
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), text)
    finally:
        p.restore()
    return r


def paint_corner(p, tags, x=10, y=10, ink="#1f2d3d"):
    """The list of the tags in the upper-left corner of a view: chip, then the name.  -> the rectangle it took (an empty one when there are no tags)."""
    top = y
    p.save()
    try:
        p.setFont(_font(False, 12))
        for t in tags:
            r = paint_chip(p, x, y, t["letter"], t["colour"])
            p.setPen(QColor(ink))
            p.drawText(QPointF(r.right() + 6, r.bottom() - 4), t["name"])
            y += CHIP_H + 4
    finally:
        p.restore()
    return QRectF(x, top, 0, y - top)


def paint_on_model(p, tags, to_screen):
    """A chip at every condition that has an anchor.  `to_screen` maps the anchor to a QPointF of the view (or None).  The chips are nudged so that two conditions at the same
    place do not hide each other."""
    taken = []
    p.save()
    try:
        for t in tags:
            a = t.get("anchor")
            if a is None:
                continue
            s = to_screen(a)
            if s is None:
                continue
            w = chip_width(t["letter"])
            r = QRectF(s.x() - w / 2, s.y() - CHIP_H - 6, w, CHIP_H)
            for _ in range(8):
                if any(r.intersects(q) for q in taken):
                    r.translate(0, -(CHIP_H + 3))
                else:
                    break
            taken.append(r)
            p.setPen(QPen(QColor(t["colour"]), 1.4))
            p.drawLine(QPointF(s.x(), s.y()), QPointF(r.center().x(), r.bottom()))
            paint_chip(p, r.x(), r.y(), t["letter"], t["colour"])
    finally:
        p.restore()


def paint_tags(p, canvas, tags, to_screen):
    """Both: the list in the corner and the chips on the model."""
    if not tags:
        return
    paint_on_model(p, tags, to_screen)
    paint_corner(p, tags)


# ------------------------------------------------------------------------------------------------------------------------------ 3D picture
def corner_image(tags, dpr=1.0, width=230):
    """The corner list as a transparent QImage (logical size `width` x its own height) and its logical height: the 3D view puts it in its upper-left corner."""
    h = max(1, len(tags)) * (CHIP_H + 4) + 12
    img = QImage(int(width * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(0)
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        paint_corner(p, tags, x=6, y=6)
    finally:
        p.end()
    return img, h


class FocusMixin:
    """What a 2D drawing (PhysCanvas, BeamCanvas) needs to show only what the selected node / row of the outline is about.  The Outline sets focus (a word of
    sim_outline.FOCUS_OF), focus_item (the support / load of the selected row) and tag_list; with focus None (no outline) everything is drawn, as it always was."""
    focus = None
    focus_item = None
    tag_list = ()

    def shows(self, what):
        """Is `what` ('mesh', 'result', 'supports', 'loads') drawn now?"""
        f = self.focus
        if f is None:
            return True
        return {"mesh": f == "mesh", "result": f == "results", "supports": f in ("supports", "conditions"), "loads": f in ("loads", "conditions")}.get(what, False)

    def items_shown(self, items, what):
        """The supports / loads of the list that are drawn now: all of them under their node, only the selected one when a row is selected."""
        if not self.shows(what):
            return []
        fi = self.focus_item
        return list(items) if fi is None else [x for x in items if x is fi]

    def tag_screen(self, a):
        s_ = self.w2s(a[0], a[1])
        return s_ + self.pan_off if getattr(self, "pan_from", None) is not None else s_

    def paint_tag_chips(self, p):
        if self.tag_list:
            paint_tags(p, self, self.tag_list, self.tag_screen)

    def forced(self, focus="results"):
        """`with canvas.forced():` draws the result whatever node is selected (the pictures of an exported animation or report)."""
        return _Forced(self, focus)


class _Forced:
    def __init__(self, cv, focus):
        self.cv, self.focus = cv, focus

    def __enter__(self):
        self.old = (self.cv.focus, self.cv.focus_item, self.cv.tag_list)
        self.cv.focus, self.cv.focus_item, self.cv.tag_list = self.focus, None, ()
        return self

    def __exit__(self, *a):
        self.cv.focus, self.cv.focus_item, self.cv.tag_list = self.old
        self.cv.update()
