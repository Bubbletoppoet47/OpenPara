"""ext.add_model_trainer registers a Trainer model type; the program window asks a tab that has can_close() before closing it."""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ext
ext.MODEL_TRAINERS.clear()
ext.add_model_trainer("x", label="X", script="x.py", sizes=("n",), models_key="scratch")
assert ext.MODEL_TRAINERS["x"]["models_key"] == "scratch" and ext.MODEL_TRAINERS["x"]["sizes"] == ("n",)
from PyQt6.QtWidgets import QApplication, QWidget
app = QApplication([])
import gpd_app
class W(QWidget):
    ok = False
    def can_close(self): return self.ok
    def is_dirty(self): return False
shell = gpd_app.AppShell.__new__(gpd_app.AppShell)
w = W()
assert gpd_app.AppShell.confirm_close(shell, w) is False
w.ok = True
assert gpd_app.AppShell.confirm_close(shell, w) is True
print("ext trainers ok")
