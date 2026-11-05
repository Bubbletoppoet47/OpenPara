"""The wheel zoom strength is a setting (File > Settings > Navigation): one notch zooms by that percentage in every view that zooms with the wheel."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "shared"), os.path.join(HERE, "addons_src", "simulation"), os.path.join(HERE, "addons_src", "truss")]
from PyQt6.QtCore import QPointF, QPoint, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import settings, nav
assert settings.get("zoom_pct") == 8.0 and abs(settings.zoom_factor() - 1.08) < 1e-12, "gentler by default"
settings.set_many({"zoom_pct": 500}); assert settings.get("zoom_pct") == 30.0, "upper limit"
settings.set_many({"zoom_pct": 0}); assert settings.get("zoom_pct") == 1.0, "lower limit"
settings.set_many({"zoom_pct": 12.5}); assert abs(settings.zoom_factor() - 1.125) < 1e-12
assert abs(nav.NavHook.wheel_step() - 1.125) < 1e-12
settings.load(); assert settings.get("zoom_pct") == 12.5, "kept in settings.json"
def wheel(dy): return QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
import physics_tab, cfd_tab, beam_canvas
class Fake:
    def __init__(s): s.scale = 1.0; s.org = QPointF(0, 0); s.n = 0
    def s2w(s, p): return (0.0, 0.0)
    def invalidate(s): pass
    def update(s): pass
for mod, cls in ((physics_tab, "PhysCanvas"), (cfd_tab, "CFDCanvas"), (beam_canvas, "BeamCanvas")):
    f = Fake(); getattr(mod, cls).wheelEvent(f, wheel(120))
    assert abs(f.scale - 1.125) < 1e-9, (cls, f.scale)
    getattr(mod, cls).wheelEvent(f, wheel(-120)); assert abs(f.scale - 1.0) < 1e-9, (cls, f.scale)
    getattr(mod, cls).wheelEvent(f, wheel(60)); assert abs(f.scale - 1.125 ** 0.5) < 1e-9, "a half notch zooms half as much"
settings.set_many({"zoom_pct": 8.0})
# the settings window has the field
import settings_dialog
dlg = settings_dialog.SettingsDialog()
assert "zoom_pct" in dlg.fields and any(dlg.sections.item(i).text() == "Navigation" for i in range(dlg.sections.count()))
print("OK zoom setting")
os._exit(0)
