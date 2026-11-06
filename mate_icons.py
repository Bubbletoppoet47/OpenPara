"""
mate_icons.py - the little line icons of the Mate panel (drawn with QPainter, no image files), in the style of the FEA / CFD panel icons:
a 24 x 24 grid, one teal colour, round line ends.  icon(name) returns a QIcon (sharp on high-DPI screens too).
To add an icon for a new mate type: write a _name(p) function and add it to _DRAW.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

COLOUR = "#0e7f86"
GREY = "#8a949c"
_cache = {}


def _line(p, *pts):
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))


def _dot(p, x, y, r=1.5):
    p.save()
    p.setBrush(QBrush(QColor(COLOUR)))
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _arrow(p, x1, y1, x2, y2, h=3.0):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    a = math.atan2(y2 - y1, x2 - x1)
    _line(p, (x2 - h * math.cos(a - .5), y2 - h * math.sin(a - .5)), (x2, y2), (x2 - h * math.cos(a + .5), y2 - h * math.sin(a + .5)))


def _coincident(p):                        # a block resting flat on a longer face, with a dot where they meet
    p.drawLine(QPointF(3, 19), QPointF(21, 19))
    p.drawRect(QRectF(7, 8, 10, 11))
    _dot(p, 12, 19)


def _parallel(p):                          # two equal slanted lines
    p.drawLine(QPointF(6, 20), QPointF(14, 4))
    p.drawLine(QPointF(12, 20), QPointF(20, 4))


def _perpendicular(p):                     # two lines at a right angle with the little square
    _line(p, (5, 4), (5, 20), (21, 20))
    _line(p, (5, 14), (11, 14), (11, 20))


def _tangent(p):                           # a circle resting on a line
    p.drawLine(QPointF(2, 19), QPointF(22, 19))
    p.drawEllipse(QPointF(12, 12), 7, 7)
    _dot(p, 12, 19)


def _concentric(p):                        # two circles inside each other
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.drawEllipse(QPointF(12, 12), 4.5, 4.5)


def _lock(p):                              # a simple padlock: shackle over a body
    p.drawArc(QRectF(7, 3, 10, 12), 0, 180 * 16)
    p.drawLine(QPointF(7, 9), QPointF(7, 11))
    p.drawLine(QPointF(17, 9), QPointF(17, 11))
    p.drawRoundedRect(QRectF(5, 11, 14, 10), 2, 2)


def _distance(p):                          # two faces with a double arrow between them
    p.drawLine(QPointF(4, 3), QPointF(4, 21))
    p.drawLine(QPointF(20, 3), QPointF(20, 21))
    _arrow(p, 12, 12, 5.5, 12)
    _arrow(p, 12, 12, 18.5, 12)


def _angle(p):                             # two lines meeting with an arc between them
    _line(p, (4, 20), (20, 20))
    p.drawLine(QPointF(4, 20), QPointF(17, 6))
    p.drawArc(QRectF(-2, 14, 12, 12), 0, int(47 * 16))


def _symmetric(p):                         # a dashed mirror line with a triangle on each side
    pen = p.pen()
    p.save()
    pen2 = QPen(pen)
    pen2.setStyle(Qt.PenStyle.DashLine)
    pen2.setWidthF(1.2)
    p.setPen(pen2)
    p.drawLine(QPointF(12, 2), QPointF(12, 22))
    p.restore()
    p.drawPolygon(QPolygonF([QPointF(9, 7), QPointF(9, 17), QPointF(3, 17)]))
    p.drawPolygon(QPolygonF([QPointF(15, 7), QPointF(15, 17), QPointF(21, 17)]))


def _faces(p):                             # a surface seen at a slant
    p.drawPolygon(QPolygonF([QPointF(4, 17), QPointF(8, 7), QPointF(20, 7), QPointF(16, 17)]))


def _edges(p):                             # one bold edge
    pen = QPen(p.pen())
    pen.setWidthF(3.0)
    p.save()
    p.setPen(pen)
    p.drawLine(QPointF(5, 18), QPointF(19, 6))
    p.restore()


def _points(p):
    _dot(p, 12, 12, 3.2)


_DRAW = {"coincident": _coincident, "parallel": _parallel, "perpendicular": _perpendicular, "tangent": _tangent, "concentric": _concentric,
         "lock": _lock, "distance": _distance, "angle": _angle, "symmetric": _symmetric,
         "face": _faces, "edge": _edges, "vertex": _points}
NAMES = tuple(_DRAW)


def pixmap(name, size=48):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    p.setPen(QPen(QColor(COLOUR), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _DRAW[name](p)
    p.end()
    return pm


def icon(name):
    """The QIcon of one of NAMES (cached; needs a QApplication)."""
    if name not in _cache:
        _cache[name] = QIcon(pixmap(name))
    return _cache[name]
