"""The start-up card (the boot-screen look): the logo and the name on a dark blue panel, the tag lines, and below it a blue-grey strip with what the
program is loading right now and a block loading bar.

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
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QWidget

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 880, 400
NAVY, MID, TEAL, SKY, SNOW = "#0a2f55", "#0f4a6e", "#12b5b0", "#8fd3f4", "#f3fbff"      # the palette of the logo
DEEP, SHADOW = "#04122e", "#02091c"                  # the top of the panel, and the hard shadows
INK, BODY, LO, HI, BLUE = "#10204d", "#cbd3e0", "#7a869c", "#ffffff", "#3b6fd0"    # the look of the icons (icon_kit.py): navy, blue-grey, raised edge, block colour
SPLIT = 300                                           # the dark panel is above this line, the strip below it
LOOK = "boot"                                         # "boot": this file's card.  "classic": the previous card (splash_classic.py), kept but not used.
NAME = ("Open", "Para")
TAG1 = "Parametric by design. Open by nature."
TAG2 = "Built for the future."
TAG1_PLAYGROUND = "PLAYGROUND  -  development builds"


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
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)     # not always-on-top: other windows can cover it
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.scale = scale
        self.setFixedSize(int(W * scale), int(H * scale))
        self.status, self.frac = "Starting...", 0.0
        self.version = version_text()
        try:
            import channel
            self.playground = channel.is_playground()
            self.mode_text = "full dev" if channel.is_full_dev() else "testing"
        except Exception:  # noqa: BLE001
            self.playground = False
            self.mode_text = ""
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
        f.setPixelSize(max(1, int(round(px))))               # (in card units: the painter is already scaled to the window)
        f.setWeight(QFont.Weight(weight))
        f.setItalic(italic)                                # both Lora files are the family "Lora": the italic one is picked by the italic flag
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        return f

    def background(self):
        """The parts that never change, drawn once: the dark panel with its grid, the teal stripe, the blue-grey strip."""
        s = self.scale
        pm = QPixmap(int(W * s), int(H * s))
        pm.fill(QColor(BODY))
        p = QPainter(pm)
        p.scale(s, s)
        g = QLinearGradient(0, 0, 0, SPLIT)
        g.setColorAt(0.0, QColor(DEEP))
        g.setColorAt(0.55, QColor(NAVY))
        g.setColorAt(1.0, QColor(MID))
        p.fillRect(QRectF(0, 0, W, SPLIT), QBrush(g))
        c = QColor(SKY)
        c.setAlphaF(0.13)
        for x in range(0, W + 1, 28):                                     # the grid: one pixel lines
            p.fillRect(QRectF(x, 0, 1, SPLIT), c)
        for y in range(0, SPLIT, 28):
            p.fillRect(QRectF(0, y, W, 1), c)
        p.fillRect(QRectF(0, SPLIT - 4, W, 4), QColor(TEAL))               # the stripe between the two, with a lit top edge and a dark bottom edge
        p.fillRect(QRectF(0, SPLIT - 4, W, 1), QColor("#7ee8e3"))
        p.fillRect(QRectF(0, SPLIT - 1, W, 1), QColor("#08716e"))
        p.fillRect(QRectF(0, SPLIT, W, 1), QColor(HI))
        p.end()
        return pm

    def sunken(self, p, r):
        """A sunken box (white inside) like the edit boxes of the window."""
        x, y, w, h = r.x(), r.y(), r.width(), r.height()
        p.fillRect(r, QColor(HI))
        p.fillRect(QRectF(x, y, w, 1), QColor(LO))                          # outer edge: dark top and left, light bottom and right
        p.fillRect(QRectF(x, y, 1, h), QColor(LO))
        p.fillRect(QRectF(x, y + h - 1, w, 1), QColor(HI))
        p.fillRect(QRectF(x + w - 1, y, 1, h), QColor(HI))
        p.fillRect(QRectF(x + 1, y + 1, w - 2, 1), QColor(INK))             # inner edge: navy top and left
        p.fillRect(QRectF(x + 1, y + 1, 1, h - 2), QColor(INK))

    def paintEvent(self, _ev):
        if self.bg is None:
            self.bg = self.background()
        s = self.scale
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.drawPixmap(0, 0, self.bg)
        p.scale(s, s)
        # logo with a hard shadow
        lx, ly, lw = 70.0, 62.0, 150.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SHADOW))
        p.drawRoundedRect(QRectF(lx + 5, ly + 5, lw, lw), lw * 48 / 256, lw * 48 / 256)
        self.logo.render(p, QRectF(lx, ly, lw, lw))
        # the name: Open (bold) + Para (italic, light blue), each with a hard shadow
        f1, f2 = self.font("up", 82, 700, spacing=1.0), self.font("it", 82, 400, italic=True, spacing=1.0)
        m1 = QFontMetricsF(f1)
        w1 = m1.horizontalAdvance(NAME[0])
        x0, base = 262.0, 136.0
        for dx, dy, c1, c2 in ((4.0, 4.0, SHADOW, SHADOW), (0.0, 0.0, "#ffffff", SKY)):
            p.setPen(QColor(c1))
            p.setFont(f1)
            p.drawText(QPointF(x0 + dx, base + dy), NAME[0])
            p.setPen(QColor(c2))
            p.setFont(f2)
            p.drawText(QPointF(x0 + w1 + dx, base + dy), NAME[1])
        # tag lines
        tag1 = (TAG1_PLAYGROUND + " (" + self.mode_text + ")") if self.playground else TAG1
        for text, ital, y, col in ((tag1, False, 181.0, "#f08a24" if self.playground else "#ffffff"), (TAG2, True, 212.0, SKY)):
            p.setFont(self.font("it" if ital else "up", 19 if not ital else 17, 400, italic=ital))
            p.setPen(QColor(SHADOW))
            p.drawText(QPointF(266.0 + 1, y + 1), text)
            p.setPen(QColor(col))
            p.drawText(QPointF(266.0, y), text)
        # the strip: what is loading now, the version, and the block bar
        sans = QFont(QApplication.font())
        sans.setPixelSize(12)
        p.setFont(sans)
        p.setPen(QColor(INK))
        p.drawText(QRectF(40, SPLIT + 12, 640, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.status)
        if self.version:
            p.drawText(QRectF(560, SPLIT + 12, 280, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"Version {self.version}")
        box = QRectF(40, SPLIT + 48, 800, 26)
        self.sunken(p, box)
        n = int((box.width() - 8) // 17)                                   # blocks 14 wide with a gap of 3
        lit = 0 if self.frac <= 0 else max(1, int(round(n * self.frac)))
        for k in range(lit):
            bx, by = box.x() + 4 + k * 17, box.y() + 5
            p.fillRect(QRectF(bx, by, 14, 16), QColor(BLUE))
            p.fillRect(QRectF(bx, by, 14, 1), QColor(255, 255, 255, 90))
            p.fillRect(QRectF(bx, by + 14, 14, 2), QColor(10, 24, 70, 90))
        p.end()


def card_class(look=None):
    """The class of the card to show: the look named, else OPENPARA_SPLASH_LOOK, else LOOK.  An unknown name gives the boot look."""
    look = (look or os.environ.get("OPENPARA_SPLASH_LOOK") or LOOK).strip().lower()
    if look == "classic":
        from splash_classic import ClassicSplash
        return ClassicSplash
    return Splash


def show(app=None):
    """Make the card and put it on the screen at once (None when it is switched off: OPENPARA_NO_SPLASH=1 or --no-splash)."""
    if os.environ.get("OPENPARA_NO_SPLASH") == "1" or "--no-splash" in sys.argv:
        return None
    try:
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry().width() if scr is not None else W
        sp = card_class()(scale=min(1.0, 0.8 * avail / W))
        sp.show()
        QApplication.processEvents()
        sp.repaint()
        QApplication.processEvents()
        return sp
    except Exception:                                                  # a start-up card must never stop the program, but say why it is missing
        import traceback
        print("splash: could not show the start-up card:\n" + traceback.format_exc(), file=sys.stderr)
        return None
