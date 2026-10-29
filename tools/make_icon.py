"""Makes OpenPara.ico (and docs/icon.png) from assets/openpara-logo.svg (large sizes) and assets/openpara-logo-small.svg (16-48 px).
Run:  QT_QPA_PLATFORM=offscreen python tools/make_icon.py        (needs PyQt6 and Pillow)"""
import io
import os

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
from PIL import Image

app = QGuiApplication([])
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
big = QSvgRenderer(os.path.join(here, "assets", "openpara-logo.svg"))
small = QSvgRenderer(os.path.join(here, "assets", "openpara-logo-small.svg"))


def draw(n):
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(0)
    g = QPainter(img)
    g.setRenderHint(QPainter.RenderHint.Antialiasing)
    (small if n <= 48 else big).render(g, QRectF(0, 0, n, n))
    g.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(ba))).convert("RGBA")


sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [draw(n) for n in sizes]
imgs[-1].save(os.path.join(here, "OpenPara.ico"), sizes=[(n, n) for n in sizes], append_images=imgs[:-1])
imgs[-1].save(os.path.join(here, "docs", "icon.png"))
print("written")
