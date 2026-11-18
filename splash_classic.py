"""splash_classic.py - the previous start-up card, kept but not used: a navy card with rounded corners, the grid fading downwards, two teal waves, the logo
with a soft shadow, "Open" (bold) + "Para" (italic) in Lora and a thin loading bar.

It is a Splash (splash.py) that only draws differently, so the version, the Playground line, the status and the loading bar behave the same.
Not active: splash.py shows its boot-screen look.  To see this one, start the program with OPENPARA_SPLASH_LOOK=classic, or set LOOK = "classic" in splash.py.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

import splash
from splash import H, MID, NAME, NAVY, SKY, SNOW, TAG1, TAG1_PLAYGROUND, TAG2, TEAL, W


class ClassicSplash(splash.Splash):
    def __init__(self, scale=1.0):
        super().__init__(scale)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)             # the rounded corners are see-through

    def background(self):
        """Card, grid (fading out downwards) and wave, drawn once."""
        s = self.scale
        pm = QPixmap(int(W * s), int(H * s))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(s, s)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, W, H), 14, 14)
        p.setClipPath(clip)
        g = QRadialGradient(QPointF(W * 0.5, H * 0.38), W * 0.62)
        g.setColorAt(0.0, QColor(MID))
        g.setColorAt(0.75, QColor(NAVY))
        g.setColorAt(1.0, QColor(NAVY))
        p.fillRect(QRectF(0, 0, W, H), QBrush(g))
        grid = QPixmap(int(W * s), int(H * s))                 # the grid on its own, then faded with a vertical mask
        grid.fill(Qt.GlobalColor.transparent)
        gp = QPainter(grid)
        gp.scale(s, s)
        c = QColor(SKY)
        c.setAlphaF(0.20)
        gp.setPen(QPen(c, 1.0))
        for x in range(0, W + 1, 28):
            gp.drawLine(x, 0, x, H)
        for y in range(0, H + 1, 28):
            gp.drawLine(0, y, W, y)
        gp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QLinearGradient(0, 0, 0, H)
        fade.setColorAt(0.0, QColor(255, 255, 255, 255))
        fade.setColorAt(1.0, QColor(255, 255, 255, 0))
        gp.fillRect(QRectF(0, 0, W, H), QBrush(fade))
        gp.end()
        p.resetTransform()
        p.drawPixmap(0, 0, grid)
        p.scale(s, s)
        wave = QColor(TEAL)
        wave.setAlphaF(0.35)
        for dy in (0, 20):                                        # two overlapping bands along the bottom
            path = QPainterPath()
            path.moveTo(0, 340 + dy)
            path.cubicTo(150, 310 + dy, 250, 390 + dy, 420, 350 + dy)
            path.cubicTo(590, 310 + dy, 700, 300 + dy, 880, 345 + dy)
            path.lineTo(W, H)
            path.lineTo(0, H)
            path.closeSubpath()
            p.fillPath(path, wave)
        p.end()
        return pm

    def paintEvent(self, _ev):
        if self.bg is None:
            self.bg = self.background()
        s = self.scale
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.drawPixmap(0, 0, self.bg)
        p.scale(s, s)
        # logo with a soft shadow
        lx, ly, lw = (W - 92) / 2, 44.0, 92.0
        for i in range(6):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 16))
            p.drawRoundedRect(QRectF(lx - i, ly + 8 - i, lw + 2 * i, lw + 2 * i), 21 + i, 21 + i)
        self.logo.render(p, QRectF(lx, ly, lw, lw))
        # the name: Open (bold) + Para (italic)
        f1, f2 = self.font("up", 56, 700, spacing=1.0), self.font("it", 56, 400, italic=True, spacing=1.0)
        w1, w2 = QFontMetricsF(f1).horizontalAdvance(NAME[0]), QFontMetricsF(f2).horizontalAdvance(NAME[1])
        x0, base = (W - (w1 + w2)) / 2, 232.0
        p.setPen(QColor(SNOW))
        p.setFont(f1)
        p.drawText(QPointF(x0, base), NAME[0])
        p.setFont(f2)
        p.drawText(QPointF(x0 + w1, base), NAME[1])
        # tag lines
        tag1 = (TAG1_PLAYGROUND + " (" + self.mode_text + ")") if self.playground else TAG1
        for text, key, wt, ital, y, col, a in ((tag1, "up", 400, False, 268.0, SNOW if not self.playground else "#f08a24", 0.95), (TAG2, "it", 600, True, 293.0, SKY, 1.0)):
            c = QColor(col)
            c.setAlphaF(a)
            p.setFont(self.font(key, 19, wt, italic=ital))
            p.setPen(c)
            p.drawText(QRectF(0, y - 18, W, 26), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)
        # loading bar and status
        bx0, bx1, by = 270.0, 610.0, 340.0
        track = QColor(SKY)
        track.setAlphaF(0.25)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(bx0, by, bx1 - bx0, 4), 2, 2)
        p.setBrush(QColor(TEAL))
        p.drawRoundedRect(QRectF(bx0, by, max(4.0, (bx1 - bx0) * self.frac), 4), 2, 2)
        st = self.status + (f"   ·   Version {self.version}" if self.version else "")
        c = QColor(SNOW)
        c.setAlphaF(0.8)
        p.setFont(self.font("up", 14, 400))
        p.setPen(c)
        p.drawText(QRectF(0, 352, W, 24), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, st)
        p.end()
