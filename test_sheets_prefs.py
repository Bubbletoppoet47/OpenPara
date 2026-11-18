"""Sheets (dev_addons/sheets): the person's own settings - ribbon icon size and text size (bounded number boxes, kept in Sheets' own file, applied at once to every
button), a damaged settings file, listeners, and the ribbon that grows and scrolls with the sizes."""
import faulthandler
import json
import os
import sys
import tempfile

faulthandler.dump_traceback_later(120, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtWidgets import QApplication, QScrollArea

app = QApplication([])
import sh_prefs as P
import sh_ribbon as R
import sh_tab as TAB

T = tempfile.mkdtemp(prefix="opara_sprefs_")
P.use_folder(T)

# ---- defaults, bounds, saving
assert P.get("ribbon_icon") == 20 and P.get("ribbon_text") == 10 and P.get("chart_preset") == "Default"
assert P.LIMITS == {"ribbon_icon": (10, 48), "ribbon_text": (8, 20)}
heard = []
P.on_change(heard.append)
assert P.set_many({"ribbon_icon": 30}) == ["ribbon_icon"] and P.get("ribbon_icon") == 30 and heard == [["ribbon_icon"]]
assert P.set_many({"ribbon_icon": 30}) == [] and len(heard) == 1                               # nothing changed: nobody is told
assert P.set_many({"ribbon_icon": 500, "ribbon_text": 1}) == ["ribbon_icon", "ribbon_text"] and P.get("ribbon_icon") == 48 and P.get("ribbon_text") == 8
assert P.set_many({"ribbon_icon": -4}) == ["ribbon_icon"] and P.get("ribbon_icon") == 10
assert P.set_many({"ribbon_icon": "twelve"}) == ["ribbon_icon"] and P.get("ribbon_icon") == 20          # not a number: back to the default
assert P.set_many({"ribbon_icon": 12.6}) == ["ribbon_icon"] and P.get("ribbon_icon") == 13
assert P.set_many({"nothing": 1}) == [] and P.get("nothing") is None
assert P.set_many({"chart_preset": "Report"}) == ["chart_preset"] and P.get("chart_preset") == "Report" and P.set_many({"chart_preset": 5}) == ["chart_preset"] and P.get("chart_preset") == "Default"
P.off_change(heard.append)
n = len(heard)
P.set_many({"ribbon_icon": 25})
assert len(heard) == n
# the file: written at once, read back by a fresh start, a damaged one is the defaults
path = os.path.join(T, "prefs.json")
assert json.load(open(path))["ribbon_icon"] == 25
P.use_folder(T)
assert P.get("ribbon_icon") == 25
open(path, "w").write("{ not json")
P.use_folder(T)
assert P.get("ribbon_icon") == 20 and P.get("ribbon_text") == 10
open(path, "w").write(json.dumps({"ribbon_icon": 9999, "ribbon_text": "x", "chart_preset": 3}))
P.use_folder(T)
assert P.get("ribbon_icon") == 48 and P.get("ribbon_text") == 10 and P.get("chart_preset") == "Default"
open(path, "w").write("[1, 2]")
P.use_folder(T)
assert P.get("ribbon_icon") == 20
P.use_folder(os.path.join(T, "new folder"))                                                     # a folder that does not exist yet is made when saving
P.set_many({"ribbon_text": 14})
assert os.path.isfile(os.path.join(T, "new folder", "prefs.json")) and P.get("ribbon_text") == 14
P.reset()
assert P.get("ribbon_icon") == 20 and P.get("ribbon_text") == 10
P.use_folder(os.path.join(T, "tab"))

# ---- one button: two sizes, and the glyph and the label are drawn
b = R.RibbonButton("◔", "Insert\nchart", 20, 10)
small = b.sizeHint()
b.set_sizes(48, 20)
big = b.sizeHint()
assert big.width() > small.width() and big.height() > small.height() and b.minimumSize() == big
b.set_sizes(10, 8)
tiny = b.sizeHint()
assert tiny.height() < small.height() and b.text() == "◔\nInsert\nchart"
b.resize(b.sizeHint())
assert not b.grab().isNull()                                                                    # (painting works at every size)
for ip, tp in ((10, 8), (48, 20), (20, 10), (48, 8), (10, 20)):
    b.set_sizes(ip, tp)
    b.resize(b.sizeHint())
    assert not b.grab().isNull()
assert R.page_height([b], 9) > b.sizeHint().height()

# ---- the window follows the settings
t = TAB.make_tab()
t.resize(1100, 700)
t.show()
assert t.ribbon_buttons and all(x.fg.pointSizeF() == 20 and x.fl.pointSizeF() == 10 for x in t.ribbon_buttons)
h0 = t.ribbon.height()
P.set_many({"ribbon_icon": 40, "ribbon_text": 16})
assert all(x.fg.pointSizeF() == 40 and x.fl.pointSizeF() == 16 for x in t.ribbon_buttons)
assert t.ribbon.height() > h0, (t.ribbon.height(), h0)
assert all(c.font().pointSizeF() == 15 for c in t.ribbon_captions)
P.set_many({"ribbon_icon": 10, "ribbon_text": 8})
assert t.ribbon.height() < h0 and all(x.fg.pointSizeF() == 10 for x in t.ribbon_buttons)
P.set_many({"ribbon_icon": 20, "ribbon_text": 10})
assert t.ribbon.height() == h0
# every ribbon page scrolls sideways when it is too wide for the window
for i in range(t.ribbon.count()):
    sc = t.ribbon.widget(i)
    assert isinstance(sc, QScrollArea) and sc.widgetResizable()
P.set_many({"ribbon_icon": 48, "ribbon_text": 20})
t.resize(700, 600)
app.processEvents()
page = t.ribbon.widget(0)
assert page.widget().minimumSizeHint().width() > page.viewport().width() and page.horizontalScrollBar().maximum() > 0, (page.widget().minimumSizeHint().width(), page.viewport().width())
P.set_many({"ribbon_icon": 20, "ribbon_text": 10})

# ---- the View tab's window: bounded boxes that apply at once and Reset
view = [t.ribbon.tabText(i) for i in range(t.ribbon.count())].index("View")
assert t.act["ribbon_size"] is not None
dlg = R.RibbonSizeDialog(t)
assert (dlg.icon.minimum(), dlg.icon.maximum()) == (10, 48) and (dlg.text.minimum(), dlg.text.maximum()) == (8, 20)
assert dlg.icon.value() == 20 and dlg.text.value() == 10
dlg.icon.setValue(44)
dlg.text.setValue(15)
assert P.get("ribbon_icon") == 44 and P.get("ribbon_text") == 15 and all(x.fg.pointSizeF() == 44 for x in t.ribbon_buttons)
dlg.icon.setValue(9999)                                                                         # the box stops at its bound
assert dlg.icon.value() == 48 and P.get("ribbon_icon") == 48
dlg.text.setValue(-5)
assert dlg.text.value() == 8
dlg.reset()
assert (dlg.icon.value(), dlg.text.value()) == (20, 10) and P.get("ribbon_icon") == 20 and P.get("ribbon_text") == 10
dlg.icon.setValue(33)
# a second window opened later starts at the saved sizes
t2 = TAB.make_tab()
assert all(x.fg.pointSizeF() == 33 for x in t2.ribbon_buttons)
# a tab that is closed no longer listens
before = len(P._listeners)
t2.shutdown()
assert len(P._listeners) == before - 1
P.set_many({"ribbon_icon": 22})
assert all(x.fg.pointSizeF() == 22 for x in t.ribbon_buttons)
t.shutdown()
print("OK test_sheets_prefs")
