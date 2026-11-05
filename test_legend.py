"""The colour scale never leaves the picture: drawn onto images from very narrow to wide, with long titles and big numbers, every non-background pixel
and the returned rectangle stay inside, and the numbers are still there."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
SIM = next(p for p in (os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "dev_addons", "simulation")) if os.path.isdir(p))
sys.path[:0] = [HERE, SIM, os.path.join(HERE, "shared")]
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import legend_draw
import physics_tab

LONG = "Von Mises equivalent stress including the stress concentration factor  [N/mm^2]"
def ink(img, margin):
    """True if any pixel within `margin` of the image edge is not white"""
    w, h = img.width(), img.height()
    for x in range(w):
        for y in range(h):
            if (x < margin or y < margin or x >= w - margin or y >= h - margin) and img.pixelColor(x, y) != QColor("white"):
                return True
    return False

for W, H in [(60, 60), (120, 150), (200, 300), (300, 400), (700, 500), (1400, 900), (260, 70)]:
    for title in ("Stress [MPa]", LONG):
        for big in (1.0, 123456789.123, -9.87654e12):
            img = QImage(W, H, QImage.Format.Format_RGB32); img.fill(QColor("white"))
            p = QPainter(img)
            labels = [(k / 5, f"{big * (1 - k / 5):.4g}") for k in range(6)]
            r = legend_draw.draw_legend(p, W, H, title, labels, physics_tab.colours, subtitle="(range of the frame shown)")
            p.end()
            assert r.left() >= 0 and r.top() >= 0 and r.right() <= W and r.bottom() <= H, (W, H, title[:8], big, r)
            assert not ink(img, 1), ("pixels on the edge", W, H, title[:8], big)
            n = sum(1 for x in range(W) for y in range(H) if img.pixelColor(x, y) != QColor("white"))
            assert n > 50, ("nothing drawn", W, H)
print("legend ok")
