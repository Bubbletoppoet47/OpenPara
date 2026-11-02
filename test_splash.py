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
assert img.pixelColor(440, 200).alpha() > 0 and img.pixelColor(0, 0).alpha() == 0       # card drawn, corners rounded away
assert 0.0 <= sp.frac <= 1.0
sp.finish()
print("splash ok", sp.version)
