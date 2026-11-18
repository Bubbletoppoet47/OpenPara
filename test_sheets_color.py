"""Sheets (dev_addons/sheets): the colour swatches - the colour picker keeps the program's look whatever colour the swatch has (it used to take the swatch's colour),
opens on the window, and remembers the person's custom colours between uses; no rule in the panel reaches the windows opened from a widget."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(120, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QColorDialog, QDialog, QLineEdit, QPushButton, QVBoxLayout, QWidget

app = QApplication([])
import sh_dialogs as D
import sh_prefs
import sh_tab as TAB

T = tempfile.mkdtemp(prefix="opara_scol_")
sh_prefs.use_folder(os.path.join(T, "prefs"))
LAV = "#cdc4ff"


def centre(w):
    w.resize(300, 200)
    w.show()
    app.processEvents()
    img = w.grab().toImage()
    return QColor(img.pixel(img.width() // 2, img.height() // 2)).name()


# ---- a dialog opened from a swatch keeps its own look
win = QWidget()
lay = QVBoxLayout(win)
sw = D.ColorButton(LAV)
lay.addWidget(sw)
win.show()
plain = QWidget()
base = centre(QDialog(plain))                                                           # a dialog with an ordinary parent
assert base != LAV
assert centre(QDialog(sw)) == base, "a dialog that is a child of the swatch must not take the swatch's colour"
assert sw.styleSheet().startswith("QPushButton#colorswatch") and LAV in sw.styleSheet() and sw.objectName() == "colorswatch"
# (the old rule, which has no target, does reach it: the check can see the fault)
old = QPushButton()
old.setStyleSheet(f"background:{LAV}; border:1px solid #8a93a3;")
assert centre(QDialog(old)) == LAV
# the swatch itself shows its colour
img = sw.grab().toImage()
assert QColor(img.pixel(img.width() // 2, img.height() // 2)).name() == LAV

# ---- pick(): the picker is on the window, starts at the swatch's colour, and the answer is kept or dropped
seen = []


def fake_exec(answer, add=None):
    """Stands in for the picker being used: `answer` is the colour chosen (None: Cancel); `add` = {slot: colour} are "Add to Custom Colors" clicks."""
    def run(self):
        seen.append((self.parent(), self.currentColor().name(), self.windowTitle(), QColorDialog.customColor(0).name(), QColorDialog.customColor(3).name()))
        for i, c in (add or {}).items():
            QColorDialog.setCustomColor(i, QColor(c))
        if answer:
            self.setCurrentColor(QColor(answer))
            return 1
        return 0
    return run


got = []
sw.picked.connect(got.append)
QColorDialog.exec = fake_exec("#336699")
sw.pick()
assert seen[-1][0] is win and seen[-1][1] == LAV and seen[-1][2] == "Colour"
assert sw.color == "#336699" and got == ["#336699"] and "#336699" in sw.styleSheet() and LAV not in sw.styleSheet()
QColorDialog.exec = fake_exec(None)                                                    # Cancel: nothing changes
sw.pick()
assert sw.color == "#336699" and got == ["#336699"]
assert D.pick_color(sw, "#102030") is None                                              # the helper the other windows use
QColorDialog.exec = fake_exec("#778899")
assert D.pick_color(sw, None).name() == "#778899" and seen[-1][1] == "#ffffff" and seen[-1][0] is win

# ---- the custom colours are remembered (they are saved when the picker closes, and given back when it opens)
for i in range(QColorDialog.customCount()):
    QColorDialog.setCustomColor(i, QColor("#ffffff"))
sh_prefs.set_many({"custom_colors": ""})
QColorDialog.exec = fake_exec(None, add={0: "#123456", 3: "#abcdef"})                  # the person adds two custom colours and cancels
sw.pick()
saved = sh_prefs.get("custom_colors").split(",")
assert saved[0] == "#123456" and saved[3] == "#abcdef" and len(saved) == QColorDialog.customCount(), saved
for i in range(QColorDialog.customCount()):                                            # a new run of the program: Qt starts with none
    QColorDialog.setCustomColor(i, QColor("#ffffff"))
sh_prefs.use_folder(os.path.join(T, "prefs"))                                          # (read from the file)
QColorDialog.exec = fake_exec(None)
sw.pick()
assert seen[-1][3] == "#123456" and seen[-1][4] == "#abcdef", seen[-1]                 # already back when the picker opens
open(os.path.join(T, "prefs", "prefs.json"), "w").write('{"custom_colors": "zzz,#112233,,not,#445566"}')    # a damaged entry is skipped
sh_prefs.use_folder(os.path.join(T, "prefs"))
D.load_custom_colors()
assert QColorDialog.customColor(1).name() == "#112233" and QColorDialog.customColor(4).name() == "#445566"

# ---- the panel: every swatch is scoped, and no rule in it reaches the windows opened from a widget
t = TAB.make_tab()
t.resize(1300, 800)
t.show()
wb, g = t.wb, t.grid
S = wb.sheet_names()[0]
for i in range(1, 7):
    wb.set_input(S, i, 1, str(i))
    wb.set_input(S, i, 2, str(i * 2))
g.select(1, 1, 6, 2)
t.chart_new()
p = t.panel
for e in p.adv_secs:
    p.adv_build(e)
p.limits.add(["L", "5", "x", "#c0392b"])
swatches = p.findChildren(D.ColorButton)
assert len(swatches) > 30, len(swatches)
assert all(b.styleSheet().startswith("QPushButton#colorswatch") for b in swatches)
p.data_range.set_state(False, "bad")                                                   # the warning and the picking outline are scoped to the box too
assert p.data_range.edit.styleSheet().startswith("QLineEdit")
p.data_range.set_picking(True)
assert p.data_range.edit.styleSheet().startswith("QLineEdit")
p.data_range.set_picking(False)
for w in p.findChildren(QLineEdit):
    ss = w.styleSheet()
    assert ss == "" or "{" in ss, ss
# the chart's own colours still reach the chart: a swatch picked in the panel sets the background of the chart and not of the window around it
p.cw["bg"].picked.emit(LAV)
p._emit_now()
ch = g.sheet_obj().charts[0]
assert ch["style"]["bg"] == LAV
fr = g.frames[ch["id"]]
fr.redraw()
import matplotlib.colors
assert matplotlib.colors.to_hex(fr.fig.get_facecolor()) == LAV
QColorDialog.exec = fake_exec(None)
p.cw["bg"].pick()
assert seen[-1][0] is t.window() and seen[-1][1] == "#ffffff"                                 # (opens on the window, at the swatch's colour)
t.shutdown()
print("OK test_sheets_color")
