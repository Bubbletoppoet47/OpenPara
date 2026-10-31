"""
icons.py - the ribbon icons, drawn in code (no image files): flat two-colour line icons with a blue accent.

icon(name) -> QIcon, name is the lower-case button label ("line", "extruded boss/base", ...); unknown names give None.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK, ACC, FILL, ACC2, RED = QColor("#2f3b52"), QColor("#2b7de9"), QColor("#cfe0fb"), QColor("#f08a24"), QColor("#d64545")
S = 40


def pen(c=INK, w=2.2, dash=False):
    p = QPen(c, w, Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    return p


def poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def dot(g, x, y, c=ACC, r=2.6):
    g.setPen(Qt.PenStyle.NoPen)
    g.setBrush(QBrush(c))
    g.drawEllipse(QPointF(x, y), r, r)
    g.setBrush(Qt.BrushStyle.NoBrush)


def arc(g, cx, cy, r, a0, a1):
    g.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(a0 * 16), int((a1 - a0) * 16))


def box3d(g, x, y, w, h, d, top=FILL, side=None, line=INK):
    """A small isometric block: front face (x, y, w, h) with depth d going up-right."""
    g.setPen(pen(line, 1.8))
    g.setBrush(QBrush(side or QColor("#9db8e3")))
    g.drawPolygon(poly([(x + w, y), (x + w + d, y - d), (x + w + d, y + h - d), (x + w, y + h)]))
    g.setBrush(QBrush(top))
    g.drawPolygon(poly([(x, y), (x + d, y - d), (x + w + d, y - d), (x + w, y)]))
    g.setBrush(QBrush(QColor("#e9f1fd")))
    g.drawRect(QRectF(x, y, w, h))
    g.setBrush(Qt.BrushStyle.NoBrush)


def draw(name, g):
    g.setBrush(Qt.BrushStyle.NoBrush)
    g.setPen(pen())
    n = name
    if n == "sketch":
        g.setPen(pen(ACC, 2.4))
        g.drawPolyline(poly([(6, 32), (6, 12), (26, 12)]))
        g.setPen(pen(INK, 2.4))
        g.drawLine(QPointF(14, 30), QPointF(32, 8))
        g.drawLine(QPointF(32, 8), QPointF(35, 11))
        g.drawLine(QPointF(35, 11), QPointF(17, 33))
        g.drawLine(QPointF(17, 33), QPointF(13, 34))
        g.drawLine(QPointF(13, 34), QPointF(14, 30))
    elif n.startswith("exit"):
        g.setPen(pen(ACC, 3))
        g.drawPolyline(poly([(8, 21), (16, 29), (33, 10)]))
    elif n == "normal to":
        g.drawRect(QRectF(8, 8, 24, 24))
        g.setPen(pen(ACC, 2.4))
        g.drawLine(QPointF(20, 4), QPointF(20, 12))
        g.drawLine(QPointF(20, 28), QPointF(20, 36))
        g.drawLine(QPointF(4, 20), QPointF(12, 20))
        g.drawLine(QPointF(28, 20), QPointF(36, 20))
    elif n == "select":
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(11, 6), (11, 30), (17, 24), (21, 33), (25, 31), (21, 22), (29, 22)]))
    elif n in ("line", "centerline"):
        g.setPen(pen(INK, 2.4, dash=(n == "centerline")))
        g.drawLine(QPointF(8, 31), QPointF(32, 9))
        dot(g, 8, 31)
        dot(g, 32, 9)
    elif n == "rectangle":
        g.setBrush(QBrush(FILL))
        g.drawRect(QRectF(7, 11, 26, 18))
        dot(g, 7, 11)
        dot(g, 33, 29)
    elif n == "circle":
        g.setBrush(QBrush(FILL))
        g.drawEllipse(QPointF(20, 20), 12, 12)
        dot(g, 20, 20)
    elif n == "arc":
        g.setPen(pen(INK, 2.6))
        arc(g, 20, 24, 14, 20, 160)
        dot(g, 6.6, 20.8)
        dot(g, 33.4, 20.8)
        dot(g, 20, 24, ACC2, 2.2)
    elif n == "slot":
        g.setBrush(QBrush(FILL))
        p = QPainterPath()
        p.addRoundedRect(QRectF(6, 12, 28, 16), 8, 8)
        g.drawPath(p)
        dot(g, 14, 20)
        dot(g, 26, 20)
    elif n == "polygon":
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(20 + 13 * math.cos(math.radians(90 + 60 * k)), 20 - 13 * math.sin(math.radians(90 + 60 * k))) for k in range(6)]))
        dot(g, 20, 20)
    elif n == "point":
        dot(g, 20, 20, INK, 4)
        g.setPen(pen(ACC, 1.8))
        g.drawLine(QPointF(8, 20), QPointF(13, 20))
        g.drawLine(QPointF(27, 20), QPointF(32, 20))
        g.drawLine(QPointF(20, 8), QPointF(20, 13))
        g.drawLine(QPointF(20, 27), QPointF(20, 32))
    elif n.startswith("sketch fillet"):
        g.setPen(pen(INK, 2.6))
        p = QPainterPath()
        p.moveTo(8, 32)
        p.lineTo(8, 18)
        p.quadTo(8, 8, 18, 8)
        p.lineTo(32, 8)
        g.drawPath(p)
        dot(g, 8, 32)
        dot(g, 32, 8)
    elif n.startswith("trim"):
        g.setPen(pen(INK, 2.4))
        g.drawLine(QPointF(6, 28), QPointF(34, 28))
        g.drawLine(QPointF(20, 8), QPointF(20, 32))
        g.setPen(pen(RED, 2.4))
        g.drawLine(QPointF(20, 28), QPointF(34, 28))
        g.setPen(pen(ACC, 1.8))
        g.drawLine(QPointF(26, 12), QPointF(34, 20))
        g.drawLine(QPointF(34, 12), QPointF(26, 20))
    elif n.startswith("offset"):
        g.setBrush(QBrush(FILL))
        g.drawRoundedRect(QRectF(12, 12, 16, 16), 4, 4)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(ACC, 2.2))
        g.drawRoundedRect(QRectF(5, 5, 30, 30), 6, 6)
    elif n.startswith("mass"):          # a balance scale
        g.setPen(pen(INK, 2.2))
        g.drawLine(QPointF(20, 8), QPointF(20, 31))
        g.drawLine(QPointF(10, 11), QPointF(30, 11))
        g.drawLine(QPointF(13, 33), QPointF(27, 33))
        for cx in (10, 30):
            g.drawLine(QPointF(cx, 11), QPointF(cx - 5, 22))
            g.drawLine(QPointF(cx, 11), QPointF(cx + 5, 22))
            g.setBrush(QBrush(FILL))
            g.drawPie(QRectF(cx - 6, 17, 12, 10), 180 * 16, 180 * 16)
        dot(g, 20, 8, ACC2)
    elif n == "measure":                 # a tape / ruler with ticks
        g.setPen(pen(INK, 2.0))
        g.setBrush(QBrush(QColor("#f6d36b")))
        g.save()
        g.translate(20, 20)
        g.rotate(-35)
        g.drawRect(QRectF(-15, -5, 30, 10))
        g.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(-12, 13, 4):
            g.drawLine(QPointF(k, -5), QPointF(k, -1 if k % 8 else 1))
        g.restore()
        dot(g, 8, 31, ACC)
        dot(g, 32, 9, ACC)
    elif n == "insert components":       # a block with a plus
        box3d(g, 6, 16, 16, 14, 7)
        g.setPen(pen(ACC, 2.6))
        g.drawLine(QPointF(30, 7), QPointF(30, 21))
        g.drawLine(QPointF(23, 14), QPointF(37, 14))
    elif n == "mate":                    # two blocks hooked together
        g.setPen(pen(INK, 2.0))
        g.setBrush(QBrush(FILL))
        g.drawRect(QRectF(5, 20, 15, 14))
        g.setBrush(QBrush(QColor("#9db8e3")))
        g.drawRect(QRectF(20, 8, 15, 14))
        g.setPen(pen(ACC, 2.6))
        g.drawLine(QPointF(20, 21), QPointF(20, 21))
        dot(g, 20, 21, ACC, 3.4)
        g.drawLine(QPointF(12, 14), QPointF(18, 14))
        g.drawLine(QPointF(27, 28), QPointF(33, 28))
    elif n == "linear component pattern":    # a row of three blocks
        for k, x in enumerate((4, 15, 26)):
            box3d(g, x, 18, 8, 10, 4, top=FILL if k == 0 else QColor("#e3edfb"), side=QColor("#9db8e3") if k == 0 else QColor("#cbd9ee"),
                  line=INK if k == 0 else QColor("#7f8aa3"))
        g.setPen(pen(ACC, 2.2))
        g.drawLine(QPointF(6, 34), QPointF(33, 34))
        g.drawLine(QPointF(29, 31), QPointF(33, 34))
        g.drawLine(QPointF(29, 37), QPointF(33, 34))
    elif n == "edit component":          # a block with a pencil
        box3d(g, 6, 16, 17, 14, 7)
        g.setPen(pen(ACC2, 2.6))
        g.drawLine(QPointF(24, 30), QPointF(35, 12))
        g.setPen(pen(INK, 1.6))
        g.drawLine(QPointF(24, 30), QPointF(22, 34))
    elif n == "tab tree":                # hierarchy
        g.setPen(pen(INK, 2.2))
        g.drawLine(QPointF(10, 9), QPointF(10, 30))
        for y in (17, 30):
            g.drawLine(QPointF(10, y), QPointF(18, y))
        g.setBrush(QBrush(FILL))
        g.drawRect(QRectF(5, 5, 11, 8))
        g.drawRect(QRectF(19, 13, 14, 8))
        g.setBrush(QBrush(QColor("#9db8e3")))
        g.drawRect(QRectF(19, 26, 14, 8))
    elif n == "tab properties":          # a form: label + field rows
        g.setPen(pen(INK, 2.0))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.drawRoundedRect(QRectF(5, 6, 30, 28), 3, 3)
        for k, y in enumerate((12, 20, 28)):
            g.setPen(pen(ACC, 2.2))
            g.drawLine(QPointF(9, y), QPointF(15, y))
            g.setPen(pen(INK, 1.8))
            g.drawLine(QPointF(19, y), QPointF(31, y))
    elif n == "tab configurations":      # a small table with a check mark
        g.setPen(pen(INK, 2.0))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.drawRect(QRectF(5, 7, 30, 24))
        g.setBrush(QBrush(FILL))
        g.drawRect(QRectF(5, 7, 30, 7))
        g.drawLine(QPointF(15, 7), QPointF(15, 31))
        g.drawLine(QPointF(5, 22), QPointF(35, 22))
        g.setPen(pen(QColor("#2e9e47"), 3.0))
        g.drawLine(QPointF(8, 27), QPointF(10, 29))
        g.drawLine(QPointF(10, 29), QPointF(13, 25))
    elif n == "tab equations":           # f(x) = : the globals
        g.setPen(pen(INK, 2.6))
        g.drawLine(QPointF(7, 14), QPointF(19, 14))
        g.drawLine(QPointF(7, 26), QPointF(19, 26))
        g.setPen(pen(ACC, 2.6))
        g.drawLine(QPointF(23, 10), QPointF(33, 30))
        g.drawLine(QPointF(33, 10), QPointF(23, 30))
    elif n == "tab display":             # a colourful sphere
        from PyQt6.QtGui import QRadialGradient
        gr = QRadialGradient(QPointF(16, 14), 20)
        gr.setColorAt(0, QColor("#ffffff"))
        gr.setColorAt(0.35, QColor("#66b3ff"))
        gr.setColorAt(0.7, QColor("#2e9e47"))
        gr.setColorAt(1, QColor("#d64545"))
        g.setBrush(QBrush(gr))
        g.setPen(pen(INK, 1.8))
        g.drawEllipse(QPointF(20, 20), 14, 14)
    elif n.startswith("mirror"):
        g.setPen(pen(ACC, 1.8, dash=True))
        g.drawLine(QPointF(20, 4), QPointF(20, 36))
        g.setPen(pen(INK, 2.2))
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(6, 28), (16, 28), (16, 12)]))
        g.setBrush(QBrush(QColor("#e8eefb")))
        g.drawPolygon(poly([(34, 28), (24, 28), (24, 12)]))
    elif n.startswith("sketch pattern") or n == "linear pattern":
        for k in range(3):
            g.setBrush(QBrush(FILL if k == 0 else QColor("#e8eefb")))
            g.drawRect(QRectF(5 + 11 * k, 14 + (0 if k == 0 else 0), 8, 12))
    elif n.startswith("move"):
        g.setPen(pen(ACC, 2.4))
        for a, b in (((20, 5), (20, 35)), ((5, 20), (35, 20))):
            g.drawLine(QPointF(*a), QPointF(*b))
        for p in ((20, 5), (20, 35), (5, 20), (35, 20)):
            dot(g, p[0], p[1], ACC, 3)
    elif n == "construction":
        g.setPen(pen(INK, 2.4, dash=True))
        g.drawLine(QPointF(6, 30), QPointF(34, 10))
    elif n.startswith("convert"):
        box3d(g, 8, 18, 16, 14, 8)
        g.setPen(pen(ACC, 2.6))
        g.drawPolyline(poly([(8, 18), (16, 10), (32, 10)]))
        dot(g, 32, 10, ACC, 3)
    elif n.startswith("add relation"):
        g.setPen(pen(INK, 2.4))
        g.drawLine(QPointF(8, 30), QPointF(8, 10))
        g.drawLine(QPointF(8, 30), QPointF(30, 30))
        g.setPen(pen(ACC, 2.2))
        g.drawRect(QRectF(8, 24, 6, 6))
    elif n == "dimension":
        g.setPen(pen(INK, 2))
        g.drawLine(QPointF(8, 28), QPointF(8, 20))
        g.drawLine(QPointF(32, 28), QPointF(32, 20))
        g.setPen(pen(ACC, 2.2))
        g.drawLine(QPointF(8, 24), QPointF(32, 24))
        g.drawLine(QPointF(8, 24), QPointF(13, 21))
        g.drawLine(QPointF(8, 24), QPointF(13, 27))
        g.drawLine(QPointF(32, 24), QPointF(27, 21))
        g.drawLine(QPointF(32, 24), QPointF(27, 27))
        g.setPen(pen(INK, 1.6))
        g.drawLine(QPointF(15, 10), QPointF(15, 16))
        g.drawLine(QPointF(15, 10), QPointF(25, 10))
        g.drawLine(QPointF(15, 13), QPointF(22, 13))
    elif n.startswith("extruded boss"):
        box3d(g, 7, 16, 18, 16, 9)
        g.setPen(pen(ACC, 2.4))
        g.drawLine(QPointF(16, 9), QPointF(16, 3))
        g.drawLine(QPointF(16, 3), QPointF(13, 6))
        g.drawLine(QPointF(16, 3), QPointF(19, 6))
    elif n.startswith("extruded cut"):
        box3d(g, 7, 16, 18, 16, 9)
        g.setBrush(QBrush(QColor("#ffffff")))
        g.setPen(pen(RED, 2))
        g.drawEllipse(QPointF(18, 17), 5, 3.2)
    elif n.startswith("revolved boss") or n.startswith("revolved cut"):
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(8, 8), (20, 8), (20, 32), (8, 32)]))
        g.setPen(pen(ACC, 2.2))
        arc(g, 20, 20, 13, -60, 70)
        g.setPen(pen(INK, 1.8, dash=True))
        g.drawLine(QPointF(20, 4), QPointF(20, 36))
        if "cut" in n:
            dot(g, 30, 20, RED, 3)
    elif n == "part generator":
        # a gear: toothed wheel with a hub hole
        import math as _m
        pts = []
        for k in range(24):
            r = 15 if (k // 2) % 2 == 0 else 11
            a = _m.radians(k * 15)
            pts.append((20 + r * _m.cos(a), 20 + r * _m.sin(a)))
        g.setBrush(QBrush(FILL))
        g.setPen(pen(INK, 1.8))
        g.drawPolygon(poly(pts))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.setPen(pen(ACC, 2.0))
        g.drawEllipse(QPointF(20, 20), 4.5, 4.5)
    elif n.startswith("swept"):
        # a profile at the start of a curved path, and the body that follows the path
        g.setBrush(QBrush(FILL))
        p = QPainterPath()
        p.moveTo(8, 30)
        p.cubicTo(8, 14, 20, 30, 32, 10)
        p.lineTo(35, 14)
        p.cubicTo(24, 36, 14, 18, 14, 30)
        p.closeSubpath()
        g.setPen(pen(INK, 1.8))
        g.drawPath(p)
        g.setBrush(QBrush(QColor("#ffffff")))
        g.setPen(pen(ACC, 2.2))
        g.drawEllipse(QPointF(11, 30), 4.2, 2.6)
        if "cut" in n:
            dot(g, 31, 28, RED, 3)
    elif n.startswith("lofted"):
        # two different sections joined by a blended body
        g.setBrush(QBrush(FILL))
        g.setPen(pen(INK, 1.8))
        g.drawPolygon(poly([(6, 32), (34, 32), (28, 8), (12, 8)]))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.setPen(pen(ACC, 2.2))
        g.drawRect(QRectF(13, 6, 14, 5))
        g.drawRect(QRectF(5, 28, 30, 6))
        if "cut" in n:
            dot(g, 20, 20, RED, 3)
    elif n == "fillet":
        g.setBrush(QBrush(FILL))
        p = QPainterPath()
        p.moveTo(8, 32)
        p.lineTo(8, 20)
        p.quadTo(8, 8, 20, 8)
        p.lineTo(32, 8)
        p.lineTo(32, 32)
        p.closeSubpath()
        g.drawPath(p)
    elif n == "chamfer":
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(8, 32), (8, 18), (18, 8), (32, 8), (32, 32)]))
    elif n == "shell":
        g.setBrush(QBrush(FILL))
        g.drawRect(QRectF(7, 10, 26, 22))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.drawRect(QRectF(13, 16, 14, 16))
    elif n in ("1d fea (frames)", "1d fea"):
        # a truss: triangle of bars with pin + roller supports and a load arrow
        g.setPen(pen(INK, 2.4))
        g.drawPolyline(poly([(6, 28), (20, 12), (34, 28), (6, 28)]))
        g.drawLine(QPointF(20, 12), QPointF(20, 28))
        for x, y in ((6, 28), (20, 12), (34, 28), (20, 28)):
            dot(g, x, y, INK, 2.2)
        g.setPen(pen(INK, 1.8))
        g.setBrush(QBrush(FILL))
        g.drawPolygon(poly([(6, 28), (1, 36), (11, 36)]))
        g.drawEllipse(QPointF(34, 33), 3.0, 3.0)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(RED, 2.4))
        g.drawLine(QPointF(20, 2), QPointF(20, 9))
        g.drawPolyline(poly([(17, 6), (20, 10), (23, 6)]))
    elif n == "2d fea":
        # a plate with a stress contour (blue -> red) under a mesh of triangles, a hole, and a load arrow
        g.setPen(pen(INK, 1.8))
        cols = ["#3b6fe0", "#3fb6c9", "#7ad06a", "#f2d544", "#f08a24", "#d64545"]
        x0, y0, w_, h_ = 6, 10, 28, 24
        for i, c in enumerate(cols):
            g.setBrush(QBrush(QColor(c)))
            g.drawRect(QRectF(x0 + i * w_ / 6, y0, w_ / 6, h_))
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(QColor(255, 255, 255, 190), 1.1))
        for i in range(1, 6):
            g.drawLine(QPointF(x0 + i * w_ / 6, y0), QPointF(x0 + i * w_ / 6 - 5, y0 + h_))
        g.drawLine(QPointF(x0, y0 + h_ / 2), QPointF(x0 + w_, y0 + h_ / 2))
        g.setPen(pen(INK, 2.0))
        g.drawRect(QRectF(x0, y0, w_, h_))
        g.setBrush(QBrush(QColor("#ffffff")))
        g.drawEllipse(QPointF(20, 22), 4.2, 4.2)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(INK, 2.2))
        g.drawLine(QPointF(5, 8), QPointF(5, 36))
        g.setPen(pen(RED, 2.4))
        g.drawLine(QPointF(35, 22), QPointF(39, 22))
        g.drawPolyline(poly([(37, 19), (39.5, 22), (37, 25)]))
    elif n == "2d cfd":
        # flow around a cylinder: streamlines that bend over and under the body, with arrow heads
        g.setPen(pen(ACC, 2.0))
        for y, bend in ((7, -6), (13, -6), (27, 6), (33, 6)):
            p = QPainterPath()
            p.moveTo(2, y)
            p.cubicTo(14, y, 14, y + bend * 0.0, 20, y + bend * 0.4)
            p.cubicTo(26, y + bend * 0.0, 26, y, 38, y)
            g.drawPath(p)
        for y in (7, 33):
            g.drawPolyline(poly([(34, y - 3), (38, y), (34, y + 3)]))
        g.setPen(pen(INK, 2.2))
        g.setBrush(QBrush(FILL))
        g.drawEllipse(QPointF(20, 20), 6.5, 6.5)
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(ACC2, 2.2))
        g.drawLine(QPointF(2, 20), QPointF(11, 20))
        g.drawPolyline(poly([(8, 17), (12, 20), (8, 23)]))
    elif n == "new render":
        # a camera with a glassy lens and a sun: photorealistic pictures
        from PyQt6.QtGui import QLinearGradient, QRadialGradient
        g.setPen(pen(ACC2, 2.0))
        for k in range(8):
            a = k * math.pi / 4
            g.drawLine(QPointF(31 + 5.0 * math.cos(a), 9 + 5.0 * math.sin(a)), QPointF(31 + 7.6 * math.cos(a), 9 + 7.6 * math.sin(a)))
        g.setPen(Qt.PenStyle.NoPen)
        sg = QRadialGradient(QPointF(30, 8), 5)
        sg.setColorAt(0, QColor("#ffe27a"))
        sg.setColorAt(1, QColor("#f4a21a"))
        g.setBrush(QBrush(sg))
        g.drawEllipse(QPointF(31, 9), 3.8, 3.8)
        g.setPen(pen(INK, 2.0))
        bg = QLinearGradient(QPointF(0, 14), QPointF(0, 35))
        bg.setColorAt(0, QColor("#e9f1fd"))
        bg.setColorAt(1, QColor("#a9c5ee"))
        g.setBrush(QBrush(bg))
        p = QPainterPath()
        p.addRoundedRect(QRectF(4, 15, 28, 19), 3.5, 3.5)
        g.drawPath(p)
        g.setBrush(QBrush(QColor("#a9c5ee")))
        g.drawPolygon(poly([(10, 15), (12.5, 11), (19, 11), (21.5, 15)]))
        lg = QRadialGradient(QPointF(16, 22), 8)
        lg.setColorAt(0, QColor("#7fc4ff"))
        lg.setColorAt(0.6, QColor("#2b7de9"))
        lg.setColorAt(1, QColor("#14336b"))
        g.setBrush(QBrush(lg))
        g.setPen(pen(INK, 2.0))
        g.drawEllipse(QPointF(18, 25), 7.2, 7.2)
        g.setPen(Qt.PenStyle.NoPen)
        g.setBrush(QBrush(QColor(255, 255, 255, 200)))
        g.drawEllipse(QPointF(15.6, 22.4), 2.1, 1.5)
        g.setBrush(QBrush(ACC2))
        g.drawEllipse(QPointF(28, 19), 1.5, 1.5)
    elif n in ("hole wizard", "wrap", "boundary boss/base",
               "boundary cut", "rib", "draft", "intersect"):
        g.setPen(pen(QColor("#9aa3b5"), 2))
        g.setBrush(QBrush(QColor("#eef1f7")))
        g.drawRect(QRectF(9, 9, 22, 22))
    elif n == "reference geometry":
        # a tilted plane with its grid, an axis through it, and the point where they meet
        g.setPen(pen(ACC, 2.0))
        g.setBrush(QBrush(QColor(207, 224, 251, 215)))
        g.drawPolygon(poly([(3, 29), (12, 14), (37, 14), (28, 29)]))
        g.setBrush(Qt.BrushStyle.NoBrush)
        g.setPen(pen(QColor("#7fa6e6"), 1.2))
        g.drawLine(QPointF(7.5, 21.5), QPointF(32.5, 21.5))
        g.drawLine(QPointF(20.0, 14), QPointF(15.5, 29))
        g.drawLine(QPointF(28.5, 14), QPointF(21.5, 29))
        g.setPen(pen(ACC2, 2.2))
        g.drawLine(QPointF(20.5, 4), QPointF(20.5, 36))
        g.drawLine(QPointF(20.5, 4), QPointF(17.5, 8.5))
        g.drawLine(QPointF(20.5, 4), QPointF(23.5, 8.5))
        dot(g, 20.5, 21.5, INK, 2.8)
    else:
        return False
    return True


_cache = {}


def icon(name, size=40):
    key = (name.lower().replace("\n", " "), size)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    g = QPainter(pm)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    g.scale(size * 2 / S, size * 2 / S)
    ok = draw(key[0], g)
    g.end()
    ic = QIcon(pm) if ok else None
    _cache[key] = ic
    return ic
