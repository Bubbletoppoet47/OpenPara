"""The start-up card: the logo, the name, the tag line, a loading bar and what the program is loading right now.

    sp = splash.show(app)          # first thing after QApplication exists, before the slow imports
    sp.step("Loading geometry kernel...", 0.2)
    ...
    sp.finish(main_window)         # closes it when the window is up

Only PyQt6 is imported here, so the card is on the screen long before the geometry kernel and the 3D view have loaded.  The version is read
from version.py (the same file the updater and Help > About use), so it is always the version of the program that is starting.
Lora (SIL Open Font License, see assets/fonts) is bundled so the card looks the same on every computer."""
import os
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QWidget

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 880, 400
NAVY, MID, TEAL, SKY, SNOW = "#0a2f55", "#0f4a6e", "#12b5b0", "#8fd3f4", "#f3fbff"      # the palette of the logo
NAME = ("Open", "Para")
TAG1 = "Parametric by design. Open by nature."
TAG2 = "Built for the future."
TAG1_PLAYGROUND = "PLAYGROUND  -  development builds, for testing"


def asset(*parts):
    return os.path.join(HERE, "assets", *parts)


def version_text():
    try:                                   # by file, so no other module called "version" on the path can be picked up
        import importlib.util
        spec = importlib.util.spec_from_file_location("_op_version", os.path.join(HERE, "version.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return str(mod.__version__)
    except Exception:
        try:
            import version
            return str(version.__version__)
        except Exception:
            return ""


class Splash(QWidget):
    def __init__(self, scale=1.0):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.scale = scale
        self.setFixedSize(int(W * scale), int(H * scale))
        self.status, self.frac = "Starting...", 0.0
        self.version = version_text()
        try:
            import channel
            self.playground = channel.is_playground()
        except Exception:  # noqa: BLE001
            self.playground = False
        fams = {}
        for fn, key in (("Lora-Variable.ttf", "up"), ("Lora-Italic-Variable.ttf", "it")):
            i = QFontDatabase.addApplicationFont(asset("fonts", fn))
            fams[key] = (QFontDatabase.applicationFontFamilies(i) or ["serif"])[0] if i >= 0 else "serif"
        self.fam = fams
        self.logo = QSvgRenderer(asset("openpara-logo.svg"))
        self.bg = None
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.x() + (g.width() - self.width()) // 2, g.y() + (g.height() - self.height()) // 2)

    # ------------------------------------------------------------------------------------------------------------ what is shown
    def step(self, text, frac=None):
        """What is loading now (and how far along, 0..1).  Repaints at once, so it shows even while the next import blocks."""
        self.status = text
        if frac is not None:
            self.frac = max(0.0, min(1.0, frac))
        self.repaint()
        QApplication.processEvents()

    def finish(self, widget=None):
        self.close()
        if widget is not None:
            widget.raise_()
            widget.activateWindow()

    # ------------------------------------------------------------------------------------------------------------ drawing
    def font(self, key, px, weight=400, italic=False, spacing=0.0):
        f = QFont(self.fam["it" if italic else "up"])
        f.setPixelSize(max(1, int(round(px * self.scale))))
        f.setWeight(QFont.Weight(weight))
        f.setItalic(False)                                 # the italic file is its own family
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing * self.scale)
        return f

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
            sh = QColor(0, 0, 0, 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sh)
            p.drawRoundedRect(QRectF(lx - i, ly + 8 - i, lw + 2 * i, lw + 2 * i), 21 + i, 21 + i)
        self.logo.render(p, QRectF(lx, ly, lw, lw))
        # the name: Open (bold) + Para (italic)
        f1, f2 = self.font("up", 56, 700, spacing=1.0), self.font("it", 56, 400, spacing=1.0)
        m1, m2 = QFontMetricsF(f1), QFontMetricsF(f2)
        w1, w2 = m1.horizontalAdvance(NAME[0]) / s, m2.horizontalAdvance(NAME[1]) / s
        x0 = (W - (w1 + w2)) / 2
        base = 232.0
        p.setPen(QColor(SNOW))
        p.setFont(f1)
        p.drawText(QPointF(x0, base), NAME[0])
        p.setFont(f2)
        p.drawText(QPointF(x0 + w1, base), NAME[1])
        # tag lines
        for text, key, wt, ital, y, col, a in ((TAG1_PLAYGROUND if self.playground else TAG1, "up", 400, False, 268.0, SNOW if not self.playground else "#f08a24", 0.95), (TAG2, "it", 600, True, 293.0, SKY, 1.0)):
            f = self.font(key, 19, wt)
            c = QColor(col)
            c.setAlphaF(a)
            p.setFont(f)
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


def show(app=None):
    """Make the card and put it on the screen at once (None when it is switched off: OPENPARA_NO_SPLASH=1 or --no-splash)."""
    if os.environ.get("OPENPARA_NO_SPLASH") == "1" or "--no-splash" in sys.argv:
        return None
    try:
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry().width() if scr is not None else W
        sp = Splash(scale=min(1.0, 0.8 * avail / W))
        sp.show()
        QApplication.processEvents()
        sp.repaint()
        QApplication.processEvents()
        return sp
    except Exception:                                                  # a start-up card must never stop the program, but say why it is missing
        import traceback
        print("splash: could not show the start-up card:\n" + traceback.format_exc(), file=sys.stderr)
        return None
