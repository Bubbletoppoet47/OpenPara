"""
sim_icons.py - the little icons of the FEA / CFD panels.  With a core that has the icon kit (icon_kit.py) they are drawn by it, in the program's one
icon look; with an older core the QPainter drawings below are used, so the add-on still works there.

Each icon is drawn on a 24 x 24 grid in one colour; icon(name) returns a QIcon (sharp on high-DPI screens too).
The first group are drawn from Ian's own sketches (made symmetrical): pressure, pressure_cfd, fixed, bolt, screw, contact, line_load, ux, uy, joints.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

COLOUR = "#0e7f86"
NAMES = ("pressure_cfd", "pressure", "fixed", "bolt", "screw", "contact", "line_load", "ux", "uy", "force", "moment", "wind", "snow",
         "pinned", "pinned_joint", "rigid_joint", "disp")
_cache = {}


def _arrow(p, x1, y1, x2, y2, h=3.2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    a = math.atan2(y2 - y1, x2 - x1)
    pts = [QPointF(x2 - h * math.cos(a - .5), y2 - h * math.sin(a - .5)), QPointF(x2, y2), QPointF(x2 - h * math.cos(a + .5), y2 - h * math.sin(a + .5))]
    p.drawPolyline(QPolygonF(pts))


def _ticks(p, y, xs, n=3.5):
    for x in xs:
        p.drawLine(QPointF(x, y), QPointF(x - n, y + n + 1))


def _line(p, *pts):
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


def _rect(p, x, y, w, h):
    p.drawRect(QRectF(x, y, w, h))


def _pressure_cfd(p):
    p.save()
    p.translate(12, 12)
    p.rotate(45)
    p.drawRect(QRectF(-3, -3, 6, 6))
    p.restore()
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        _arrow(p, 12 - 9 * sx, 12 - 9 * sy, 12 - 3.8 * sx, 12 - 3.8 * sy)


def _pressure(p):
    p.save()
    p.translate(12, 16.3)
    p.rotate(-20)
    p.drawRoundedRect(QRectF(-9, -1.3, 18, 2.6), 1.3, 1.3)
    p.restore()
    for x, ye in ((5, 17.3), (9.7, 15.6), (14.3, 13.9), (19, 12.2)):
        _arrow(p, x, 2.5, x, ye - 3.0, 2.0)


def _fixed(p):
    _line(p, (3, 8), (21, 8))
    _ticks(p, 8, [7, 11, 15, 19])


def _bolt(p):
    _line(p, (8, 3), (8, 21))
    _line(p, (16, 3), (16, 21))
    _rect(p, 2.5, 8, 5.5, 8)
    _rect(p, 16, 8, 5.5, 8)
    _line(p, (8, 10.8), (16, 10.8))
    _line(p, (8, 13.2), (16, 13.2))


def _screw(p):
    _line(p, (8, 3), (8, 21))
    _line(p, (16, 3), (16, 21))
    _rect(p, 16, 8, 5.5, 8)
    _line(p, (8, 10.8), (16, 10.8))
    _line(p, (8, 13.2), (16, 13.2))


def _contact(p):
    _rect(p, 8.5, 5, 7, 8)
    _line(p, (3, 13), (21, 13))
    _ticks(p, 13, [10.5, 13.5, 16.5], 3.2)


def _line_load(p):
    _line(p, (3, 19), (21, 19))
    for x in (5, 8.5, 12, 15.5, 19):
        _arrow(p, x, 3, x, 16.6, 2.0)


def _ux(p):
    _arrow(p, 12, 12, 21, 12)
    _arrow(p, 12, 12, 3, 12)
    pen = QPen(p.pen())
    pen.setWidthF(2.2)
    p.setPen(pen)
    _line(p, (10, 15.4), (14, 8.6))


def _uy(p):
    _arrow(p, 12, 12, 12, 3)
    _arrow(p, 12, 12, 12, 21)
    pen = QPen(p.pen())
    pen.setWidthF(2.2)
    p.setPen(pen)
    _line(p, (8.6, 14), (15.4, 10))


def _force(p):
    _arrow(p, 3, 12, 21, 12)


def _disp(p):
    """Displacement: a held base and a point that has been moved off it by an arrow (the base is the support, the arrow is how far it is moved)."""
    _line(p, (3, 19), (21, 19))
    _ticks(p, 19, [7, 11, 15, 19], n=2.6)
    p.drawEllipse(QPointF(7, 12), 2.2, 2.2)
    _arrow(p, 10.2, 12, 20, 12)
    _line(p, (7, 14.2), (7, 19))


def _moment(p):
    path = QPainterPath()
    path.arcMoveTo(QRectF(4.5, 4.5, 15, 15), 31.6)
    path.arcTo(QRectF(4.5, 4.5, 15, 15), 31.6, 313)
    p.drawPath(path)
    _arrow(p, 18, 6.5, 19.6, 9.2)


def _wind(p):
    path = QPainterPath()
    path.moveTo(3, 8)
    path.lineTo(14, 8)
    path.arcTo(QRectF(11.5, 3, 5, 5), 270, 270)
    path.moveTo(3, 13)
    path.lineTo(18, 13)
    path.arcTo(QRectF(15.5, 13, 5, 5), 90, -270)
    path.moveTo(3, 18)
    path.lineTo(10, 18)
    p.drawPath(path)


def _snow(p):
    _line(p, (12, 3), (12, 21))
    _line(p, (4.2, 7.5), (19.8, 16.5))
    _line(p, (4.2, 16.5), (19.8, 7.5))


def _pinned(p):
    _line(p, (12, 6), (7.5, 14), (16.5, 14), (12, 6))
    _line(p, (4, 14), (20, 14))
    _ticks(p, 14, [7, 11, 15, 19], 3)


def _pinned_joint(p):
    pen = QPen(p.pen())
    pen.setWidthF(2.0)
    p.setPen(pen)
    p.drawEllipse(QPointF(12, 12), 6.5, 6.5)


def _rigid_joint(p):
    p.setBrush(QBrush(QColor("#8a949c")))
    p.setPen(QPen(QColor("#5d6770"), 1.6))
    p.drawEllipse(QPointF(12, 12), 6.5, 6.5)


_DRAW = {"pressure_cfd": _pressure_cfd, "pressure": _pressure, "fixed": _fixed, "bolt": _bolt, "screw": _screw, "contact": _contact,
         "line_load": _line_load, "ux": _ux, "uy": _uy, "force": _force, "moment": _moment, "wind": _wind, "snow": _snow,
         "pinned": _pinned, "pinned_joint": _pinned_joint, "rigid_joint": _rigid_joint, "disp": _disp}
assert set(_DRAW) == set(NAMES)


try:
    import icon_kit                  # the core's icon look (0.8.7 on); an older core has no kit and the drawings below are used
    if not icon_kit.has("l_bolt"):
        icon_kit = None
except Exception:                    # noqa: BLE001 (any failure: fall back to the drawings below)
    icon_kit = None


def _legacy_pixmap(name, size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(COLOUR), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _DRAW[name](p)
    p.end()
    return pm


def _kit_has(name):
    """The core's icon kit has this icon (an icon added by an add-on after the kit was made is drawn by the drawings below)."""
    return icon_kit is not None and icon_kit.has("l_" + name)


def pixmap(name, size=48, ratio=2):
    if _kit_has(name):
        return icon_kit.pixmap("l_" + name, size, ratio)
    return _legacy_pixmap(name, size)


def icon(name):
    """The QIcon of one of NAMES (cached; needs a QApplication)."""
    if name not in _cache:
        _cache[name] = icon_kit.qicon("l_" + name, 24) if _kit_has(name) else QIcon(_legacy_pixmap(name, 48))
    return _cache[name]
