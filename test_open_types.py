"""File > Open lists the simulation files (*.gps) when the Simulation add-on is available (catalog, installed or in the development folder), and does not
when it is not; the parts / assemblies entries stay."""
import os, sys, json, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(); os.environ["OPARA_USER_DIR"] = UD
os.environ["OPARA_CHANNEL"] = "release"; os.environ["OPARA_NO_UPDATE"] = "1"
DEV = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import addons, gpd_app
from PyQt6.QtWidgets import QApplication
app = QApplication([])
shell = gpd_app.AppShell.__new__(gpd_app.AppShell)                      # open_filter needs no window

def flt():
    return gpd_app.AppShell.open_filter(shell)

here_has = "simulation" in addons.known()                               # true once Simulation is in the catalog (or the folder of the program)
f = flt()
assert "*.gpd" in f and "*.gpa" in f and "Part (*.gpd)" in f and "Assembly (*.gpa)" in f
assert ("*.gps" in f) == here_has and (("Simulation (*.gps)" in f) == here_has), f
# the development folder makes it available
os.makedirs(os.path.join(DEV, "simulation")); json.dump({"name": "Simulation"}, open(os.path.join(DEV, "simulation", "addon.json"), "w"))
os.environ["OPARA_DEV_ADDONS"] = DEV
assert "simulation" in addons.known()
f = flt()
assert "*.gps" in f and "Simulation (*.gps)" in f and f.split(";;")[0].startswith("All supported files (") and "*.gps" in f.split(";;")[0], f
assert f.count("*.gps") == 2                                            # once in "All supported files", once in its own entry
# render is not offered while its add-on is unknown
assert "*.gpr" not in f or "render" in addons.known()
print("OK open types")
os._exit(0)
