"""Starting the program (python gpd_app.py, which is what the Start-menu shortcut runs) shows the start-up card BEFORE the slow imports,
fills its status while it loads, and closes it once the main window is up.  Importing gpd_app (tests, CI) shows nothing."""
import os, sys, runpy, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PyQt6.QtWidgets import QApplication, QWidget
import splash, version

# 1. a plain import opens no card and no application
import subprocess
r = subprocess.run([sys.executable, "-c", "import gpd_app; from PyQt6.QtWidgets import QApplication; "
                    "assert gpd_app.SPLASH is None and QApplication.instance() is None; print('import quiet')"],
                   cwd=HERE, capture_output=True, text=True, env=dict(os.environ))
assert "import quiet" in r.stdout, r.stdout + r.stderr


def launch(argv):
    """Run gpd_app.py as __main__ with the event loop replaced by 'return at once'; record what happened."""
    log = {"shown_before_heavy": None, "steps": [], "finished": False, "window": None}
    real_show, real_step, real_finish = splash.show, splash.Splash.step, splash.Splash.finish

    def show(app=None):
        sp = real_show(app)
        log["shown_before_heavy"] = None if sp is None else not any(m in sys.modules for m in ("pm_app", "build123d", "pyvista", "addons"))
        log["card_visible"] = sp is not None and sp.isVisible()
        log["card_version"] = None if sp is None else sp.version
        return sp

    def step(self, text, frac=None):
        log["steps"].append((text, frac))
        return real_step(self, text, frac)

    def finish(self, widget=None):
        log["finished"] = True
        log["window"] = widget
        log["visible_window"] = widget is not None and widget.isVisible()
        return real_finish(self, widget)
    splash.show, splash.Splash.step, splash.Splash.finish = show, step, finish
    QApplication.exec = staticmethod(lambda: 0)
    for m in ("pm_app", "build123d", "pyvista", "addons", "gpd_app", "ext"):
        sys.modules.pop(m, None)                                  # a fresh start, as when the program is launched
    sys.argv = ["gpd_app.py"] + argv
    try:
        runpy.run_path(os.path.join(HERE, "gpd_app.py"), run_name="__main__")
    except SystemExit:
        pass
    finally:
        splash.show, splash.Splash.step, splash.Splash.finish = real_show, real_step, real_finish
    return log


log = launch([])
print(log["steps"])
assert log["shown_before_heavy"] is True, "the card must be on screen before the geometry kernel / 3D view / add-ons are imported"
assert log["card_visible"] and log["card_version"] == version.__version__
assert [t for t, _ in log["steps"]][:3] == ["Loading add-ons...", "Loading geometry kernel...", "Loading settings and units..."], log["steps"]
fr = [f for _, f in log["steps"]]
assert fr == sorted(fr) and 0 < fr[0] < fr[-1] < 1, fr
assert log["finished"] and log["visible_window"], "the card closes only when the window is up"
print("card first, steps in order, closed when the window shows")

# 2. --no-splash / OPENPARA_NO_SPLASH: no card, the program still starts
log2 = launch(["--no-splash"])
assert log2["shown_before_heavy"] is None and not log2["finished"], log2
print("OK splash launch")
