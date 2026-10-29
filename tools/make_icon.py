"""Draws the OpenPara application icon (OpenPara.ico, several sizes).  Run:  QT_QPA_PLATFORM=offscreen python tools/make_icon.py"""
import io
import math
import os
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

app = QGuiApplication([])


def draw(n):
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    g = QPainter(img)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = n / 256.0
    g.scale(s, s)
    bg = QLinearGradient(0, 0, 0, 256)
    bg.setColorAt(0, QColor("#2f6fe4"))
    bg.setColorAt(1, QColor("#14336b"))
    p = QPainterPath()
    p.addRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    g.fillPath(p, QBrush(bg))
    cx, cy, r = 128, 132, 82                       # isometric cube
    pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in (-90, -30, 30, 90, 150, 210)]
    P = lambda i: QPointF(*pts[i])
    c = QPointF(cx, cy)
    g.setPen(QPen(QColor("#0d2347"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    for poly, col in (([P(0), P(1), c, P(5)], "#ffffff"), ([P(1), P(2), P(3), c], "#bcd6fb"), ([P(5), c, P(3), P(4)], "#7fb0f4")):
        g.setBrush(QBrush(QColor(col)))
        g.drawPolygon(QPolygonF(poly))
    g.setPen(QPen(QColor("#ff9d2e"), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))     # a sketch circle on the top face
    g.setBrush(Qt.BrushStyle.NoBrush)
    g.drawEllipse(QPointF(cx, cy - 41), 22, 11)
    g.end()
    return img


from PIL import Image
sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = []
for n in sizes:
    img = draw(n)
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buf, "PNG")
    imgs.append(Image.open(io.BytesIO(bytes(ba))).convert("RGBA"))
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
imgs[-1].save(os.path.join(here, "OpenPara.ico"), sizes=[(n, n) for n in sizes], append_images=imgs[:-1])
imgs[-1].save(os.path.join(here, "docs", "icon.png"))
print("written")
