"""Settings > Performance: the core limit (threads, affinity, start-up), AutoSave every (mm:ss), the slow-moment log, and the cheap tab-star timer."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import json, os, sys, tempfile, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_"); os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
import perf, settings

# ---------------------------------------------------------------- 1. the numbers
real_count = perf.core_count
perf.core_count = lambda: 8
assert perf.allowed_cores(0) == 8 and perf.allowed_cores(4) == 4 and perf.allowed_cores(99) == 8
assert perf.compute_threads(0) == 7 and perf.compute_threads(4) == 3 and perf.compute_threads(2) == 1 and perf.compute_threads(1) == 1
assert "calculations use 3" in perf.describe(4) and perf.describe(0).startswith("Auto: 8 cores")
perf.core_count = lambda: 1
assert perf.allowed_cores(0) == 1 and perf.compute_threads(0) == 1
perf.core_count = real_count

# ---------------------------------------------------------------- 2. applying it
n = perf.core_count()
r = perf.apply(0)
assert r["allowed"] == n and r["threads"] == max(1, n - 1) and os.environ["OMP_NUM_THREADS"] == str(r["threads"])
try:
    import threadpoolctl
    assert r["pool"]
    infos = [i for i in threadpoolctl.threadpool_info() if i.get("user_api") == "blas"]
    assert not infos or all(i["num_threads"] == r["threads"] for i in infos), infos
except ImportError:
    pass
if n >= 2 and perf.current_affinity() is not None:
    r1 = perf.apply(1)
    assert r1["allowed"] == 1 and r1["threads"] == 1 and perf.current_affinity() == 1 and os.environ["OPENBLAS_NUM_THREADS"] == "1", r1
    perf.apply(0)
    assert perf.current_affinity() == n, "Auto gives every core back"
# the saved choice is read at start-up
open(os.path.join(UD, "settings.json"), "w").write(json.dumps({"cores": 1}))
r = perf.startup()
assert r["allowed"] == 1 and os.environ["OMP_NUM_THREADS"] == "1"
open(os.path.join(UD, "settings.json"), "w").write("not json")
assert perf.startup()["allowed"] == n, "a damaged file means Auto"
perf.apply(0)

# ---------------------------------------------------------------- 3. the settings
assert settings.get("autosave_s") == 60.0 and settings.get("cores") == 0 and settings.get("slow_log") is False
assert settings.clamp("autosave_s", 1) == 5.0 and settings.clamp("autosave_s", 1e9) == 86400.0 and settings.clamp("autosave_s", "x") == 60.0
assert settings.clamp("cores", 999) == n and settings.clamp("cores", -3) == 0 and settings.clamp("cores", "x") == 0 and settings.clamp("cores", 1.6) == min(2, n)

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import settings_dialog as sd
for text, want in (("5:00", 300), ("0:30", 30), ("1:30:00", 5400), ("90", 90), ("90s", 90), ("5m", 300), ("1h", 3600), ("", None), ("a:b", None), ("1:2:3:4", None), ("-1:00", None)):
    assert sd.parse_duration(text) == want, (text, sd.parse_duration(text), want)
perf.follow_settings()
dlg = sd.SettingsDialog()
fa, fc = dlg.fields["autosave_s"], dlg.fields["cores"]
assert fa.edit.text() == "1:00" and fc.edit.text() == "Auto"
fa.edit.setText("5:00"); fa.edit.textEdited.emit("5:00"); fa.edit.editingFinished.emit()
assert fa.value == 300.0 and fa.edit.text() == "5:00"
fa.edit.setText("0:01"); fa.edit.editingFinished.emit()
assert fa.value == 5.0 and fa.edit.text() == "0:05" and "Held" in fa.note.text()
fa.edit.setText("1:05:00"); fa.edit.editingFinished.emit()
assert fa.value == 3900.0 and fa.edit.text() == "1:05:00"
fc.edit.setText("1"); fc.edit.textEdited.emit("1"); fc.edit.editingFinished.emit()
assert fc.value == 1 and "1 of" in dlg.cores_note.text() or n == 1
fc.edit.setText("auto"); fc.edit.editingFinished.emit()
assert fc.value == 0 and fc.edit.text() == "Auto"
dlg.slow.setChecked(True)
fa.set_value(300.0); fc.set_value(1 if n >= 2 else 0)
dlg.apply()
assert settings.get("autosave_s") == 300.0 and settings.get("slow_log") is True
assert json.load(open(os.path.join(UD, "settings.json")))["autosave_s"] == 300.0
# ... and the change reaches the program: the core limit is applied when the setting changes
assert perf.slow_watch() is not None and perf.slow_watch().running, "the slow watch starts with the setting"
if n >= 2 and perf.current_affinity() is not None:
    assert perf.current_affinity() == 1
settings.set_many({"cores": 0, "slow_log": False})
assert perf.current_affinity() in (n, None) and not perf.slow_watch().running
dlg.reset_defaults(); assert fa.value == 60.0 and fc.value == 0 and not dlg.slow.isChecked()

# ---------------------------------------------------------------- 4. the slow-moment log
log = os.path.join(UD, "mine.log")
w = perf.SlowWatch(threshold=0.12, beat_ms=20, path=log)
w.start()
QTest.qWait(150)
assert not os.path.exists(log), "a quiet window writes nothing"


def blocker_function():
    time.sleep(0.5)


QTimer.singleShot(0, blocker_function)
QTest.qWait(900)
w.stop()
text = open(log).read()
assert "window blocked for" in text and "blocker_function" in text and w.count >= 1, text
assert 0.3 < float(text.split("blocked for ")[1].split(" s")[0]) < 0.9, text

# ---------------------------------------------------------------- 5. the tab-star timer: only the tab on screen, spaced out by its own cost
import gpd_app
sh = gpd_app.AppShell()
sh.new_part(); sh.new_part(); sh.new_part()
tabs = [sh.tabs.widget(i) for i in range(sh.tabs.count())]
calls = {id(t): 0 for t in tabs}
for t in tabs:
    t.is_dirty = (lambda t=t: (calls.__setitem__(id(t), calls[id(t)] + 1), time.sleep(0.05), True)[2])
sh.tabs.setCurrentIndex(1)
for t in tabs:
    calls[id(t)] = 0
sh._title_next = 0.0
sh.tick_titles()
assert calls[id(tabs[1])] == 1 and calls[id(tabs[0])] == 0 and calls[id(tabs[2])] == 0, "the timer asks the tab on screen only"
assert sh.tabs.tabText(1).endswith("*")
assert sh._title_next - time.monotonic() > 1.0, "a 50 ms test is spaced about 1.6 s apart (3 % of the time)"
sh.tick_titles(); assert calls[id(tabs[1])] == 1, "not again before the spacing is over"
sh._title_next = 0.0
real = QApplication.mouseButtons
from PyQt6.QtCore import Qt
QApplication.mouseButtons = staticmethod(lambda: Qt.MouseButton.LeftButton)
sh.tick_titles(); assert calls[id(tabs[1])] == 1, "not during a drag"
QApplication.mouseButtons = real
sh._title_next = 0.0
sh.tick_titles(); assert calls[id(tabs[1])] == 2
sh.refresh_titles()                                   # switching tabs and saving look at all of them
assert all(calls[id(t)] >= 1 for t in tabs) and all(sh.tabs.tabText(i).endswith("*") for i in range(3))
print("OK test_perf")
