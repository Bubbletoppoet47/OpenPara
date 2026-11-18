"""The start-up card shows the real version (read from version.py, never typed in) and renders with the bundled Lora fonts."""
import os
import sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import splash
import version

sp = splash.Splash(1.0)
assert sp.version == version.__version__ and sp.version, sp.version
assert sp.fam["up"] == "Lora" and sp.fam["it"] == "Lora", sp.fam
sp.step("Loading geometry kernel...", 0.4)
img = QImage(880, 400, QImage.Format.Format_ARGB32)
img.fill(0)
sp.render(img)
assert img.pixelColor(440, 200).alpha() > 0 and img.pixelColor(0, 0).alpha() > 0 and img.pixelColor(879, 399).alpha() > 0      # the card fills the whole window (square corners)
assert 0.0 <= sp.frac <= 1.0
from PyQt6.QtCore import Qt
fl = sp.windowFlags()
assert not (fl & Qt.WindowType.WindowStaysOnTopHint), "the card must not stay above other windows"
assert sp.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
sp.finish()

# ---- the looks (the boot look is shown; the previous one is kept, off) and the channels (the official card and the Playground card)
import tempfile
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
assert splash.LOOK == "boot" and splash.card_class() is splash.Splash
os.environ.pop("OPENPARA_SPLASH_LOOK", None)
import splash_classic
assert splash.card_class("classic") is splash_classic.ClassicSplash and issubclass(splash_classic.ClassicSplash, splash.Splash)
assert splash.card_class("nonsense") is splash.Splash
os.environ["OPENPARA_SPLASH_LOOK"] = "classic"
assert splash.card_class() is splash_classic.ClassicSplash
del os.environ["OPENPARA_SPLASH_LOOK"]


def orange(img):
    """Pixels of the Playground line's orange (#f08a24)."""
    return sum(1 for y in range(img.height()) for x in range(0, img.width()) if abs(img.pixelColor(x, y).red() - 240) < 14 and abs(img.pixelColor(x, y).green() - 138) < 14
               and abs(img.pixelColor(x, y).blue() - 36) < 24)


def draw(cls, channel, mode="testing"):
    os.environ["OPARA_CHANNEL"] = channel
    os.environ["OPARA_PLAYGROUND_MODE"] = mode
    c = cls(1.0)
    c.step("Loading geometry kernel...", 0.55)
    im = QImage(880, 400, QImage.Format.Format_ARGB32)
    im.fill(0)
    c.render(im)
    c.close()
    return c, im


for cls in (splash.Splash, splash_classic.ClassicSplash):
    rel, im_rel = draw(cls, "release")
    pg, im_pg = draw(cls, "playground")
    full, im_full = draw(cls, "playground", "full")
    assert not rel.playground and pg.playground and pg.mode_text == "testing" and full.mode_text == "full dev", cls
    assert orange(im_rel) == 0, (cls, "the official card has no Playground line")
    assert orange(im_pg) > 150 and orange(im_full) > 150, (cls, orange(im_pg))
    assert im_rel != im_pg and im_pg != im_full
    assert im_rel.pixelColor(440, 200).alpha() > 0
corner = lambda im: (im.pixelColor(0, 0).alpha(), im.pixelColor(879, 399).alpha())
assert corner(draw(splash.Splash, "release")[1]) == (255, 255), "the boot card has square corners"
assert corner(draw(splash_classic.ClassicSplash, "release")[1]) == (0, 0), "the previous card has rounded corners"
for k in ("OPARA_CHANNEL", "OPARA_PLAYGROUND_MODE"):
    os.environ.pop(k, None)
print("splash ok", sp.version)
