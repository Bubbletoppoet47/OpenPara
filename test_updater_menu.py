"""Help > "Open the updater (earlier builds, repair)..." exists exactly when the OpenPara Updater is installed next to the program, starts it (and only it:
the program keeps running), and the program puts the updater in place at its start when an update inside the program left it without one."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
WORK = tempfile.mkdtemp(prefix="opara_um_")
os.environ["OPARA_USER_DIR"] = os.path.join(WORK, "user")
os.environ["OPARA_NO_UPDATE"] = "1"
import paths
import updater
import gpd_app
from PyQt6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
ENTRY = "Open the updater (earlier builds, repair)..."
root = os.path.join(WORK, "Install")
os.makedirs(os.path.join(root, "python"))
os.makedirs(os.path.join(root, "app"))
real_code_dir = paths.CODE_DIR


def help_actions(sh):
    mb = sh.menuBar()
    hm = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Help")
    return {a.text(): a for a in hm.actions() if a.text()}


try:
    sh = gpd_app.AppShell([])
    assert ENTRY not in help_actions(sh), "a copy that runs from source has no updater entry"
    paths.CODE_DIR = os.path.join(root, "app")                       # as if installed: <root>\python and <root>\app
    sh.build_menus()
    assert ENTRY not in help_actions(sh), "an install from before the updater existed has no entry (it updates inside the program, as before)"
    os.makedirs(os.path.join(root, "updater_tool"))
    open(os.path.join(root, "updater_tool", "openpara_updater.py"), "w").write("print('updater')\n")
    sh.build_menus()
    acts = help_actions(sh)
    assert ENTRY in acts, list(acts)
    started = []
    real = subprocess.Popen
    subprocess.Popen = lambda cmd, **k: (started.append((cmd, k)), type("P", (), {"pid": 1})())[1]
    try:
        acts[ENTRY].trigger()
    finally:
        subprocess.Popen = real
    assert started and started[0][0] == [sys.executable, os.path.join(root, "updater_tool", "openpara_updater.py")] and started[0][1]["cwd"] == root, started
    assert not sh._restart_asked, "opening the updater does not close the program"
    # the start puts the updater in place when the program folder carries it
    assert "updater.seed_tool()" in inspect.getsource(gpd_app.main), "main() seeds the updater before the menus are built"
    shutil.rmtree(os.path.join(root, "updater_tool"))
    os.makedirs(os.path.join(root, "app", "updater_tool"))
    open(os.path.join(root, "app", "updater_tool", "openpara_updater.py"), "w").write("print('updater')\n")
    assert updater.seed_tool() and os.path.isfile(os.path.join(root, "updater_tool", "openpara_updater.py"))
    print("OK updater menu")
finally:
    paths.CODE_DIR = real_code_dir
    shutil.rmtree(WORK, ignore_errors=True)
