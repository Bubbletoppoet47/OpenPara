"""Sheets as a development add-on: it is found from its folder (manifest only, no core file knows it), opens in the program window as a document tab
(File > New, Open on .opsheet and .xlsx), shows the unsaved star, saves through the program's Save / Save As, closes cleanly, and uses nothing outside its folder
except the program's shared modules."""
import json
import os
import shutil
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dev_addons", "sheets")
DEV = tempfile.mkdtemp(prefix="opara_dev_")
shutil.copytree(SRC, os.path.join(DEV, "sheets"), ignore=shutil.ignore_patterns("__pycache__"))
os.environ["OPARA_DEV_ADDONS"] = DEV
os.environ["OPARA_NO_UPDATE"] = "1"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "addons_src", "partgen"))
import addons
import ext

addons.startup()
addons.register_extensions(ext)
assert addons.is_dev("sheets") and addons.is_active("sheets") and "sheets" in addons.known(), "the folder is found as a development add-on"
assert not addons.load_errors().get("sheets"), addons.load_errors()
kinds = addons.tab_kinds()
spec = kinds["sheets"]
assert (spec["label"], spec["short"], spec["module"], spec["factory"]) == ("Sheets", "Sheets", "sh_tab", "make_tab") and spec["file_types"] == [".opsheet", ".xlsx"]
assert spec["args"] == ["path"] and spec["set_host"] is True and addons.status("sheets") == "installed"
man = json.load(open(os.path.join(SRC, "addon.json")))
assert man["status"] == "workshopping" and man["name"] == "Sheets"

# nothing outside the add-on folder was needed: no core file mentions it (the add-on stays removable)
core_hits = []
for fn in os.listdir(HERE):
    if fn.endswith(".py") and not fn.startswith("test_"):
        text = open(os.path.join(HERE, fn), encoding="utf-8", errors="ignore").read()
        if "sh_tab" in text or "dev_addons/sheets" in text or "opsheet" in text:
            core_hits.append(fn)
assert core_hits == [], core_hits

import gpd_app
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

app = QApplication([])
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), QMessageBox.StandardButton.Discard)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
shell = type("Shell", (*ext.SHELL_MIXINS, gpd_app.AppShell), {})()
shell.show()
app.processEvents()

w = shell.new_addon_tab("sheets")
assert w is not None and w.kind == "sheets" and w.host is shell and w.path is None
assert shell.tabs.tabText(shell.tabs.count() - 1) == "Sheets"
g = w.grid
QTest.keyClicks(g, "5")
QTest.keyClick(g.editor, Qt.Key.Key_Return)
QTest.keyClicks(g, "=")
QTest.keyClicks(g.editor, "A1*3")
QTest.keyClick(g.editor, Qt.Key.Key_Return)
assert w.wb.value("Sheet1", 2, 1) == 15.0 and w.is_dirty()
shell.refresh_titles()
assert shell.tabs.tabText(shell.tabs.count() - 1) == "Sheets *"                       # the program's own tab strip shows the unsaved star
f = os.path.join(UD, "loads.opsheet")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (f, ""))
assert shell.save_widget(w, True) is True and os.path.isfile(f) and w.path == f and not w.is_dirty()
assert shell.tabs.tabText(shell.tabs.count() - 1) == "loads.opsheet"
n = shell.tabs.count()
assert shell.open_path(f) is w and shell.tabs.count() == n                           # the same file opens the tab that already has it

w.file_new()                                                                         # the tab's own New button
assert shell.tabs.count() == n + 1 and shell.tabs.widget(n).kind == "sheets"
shell.close_tab(n)                                                                   # clean and empty: closes without asking
assert shell.tabs.count() == n and asked == []

shutil.copy(f, os.path.join(UD, "copy.opsheet"))
w2 = shell.open_path(os.path.join(UD, "copy.opsheet"))
assert w2 is not w and w2.wb.value("Sheet1", 2, 1) == 15.0 and shell.tabs.count() == n + 1

import sh_deps
op = sh_deps.openpyxl()
if op is not None:
    wx = op.Workbook()
    wx.active.title = "Loads"
    wx.active["A1"] = 2
    wx.active["A2"] = "=A1*8"
    xl = os.path.join(UD, "book.xlsx")
    wx.save(xl)
    w3 = shell.open_path(xl)
    assert w3.kind == "sheets" and w3.wb.value("Loads", 2, 1) == 16.0 and w3.title() == "book.xlsx" and shell.tabs.count() == n + 2
    shell.refresh_titles()
    assert shell.tabs.tabText(shell.tabs.count() - 1) == "book.xlsx"                 # an Excel file opens as a workbook that is not saved yet under any name

QTest.keyClicks(w2.grid, "9")                                                         # unsaved changes: closing asks (here: Discard)
QTest.keyClick(w2.grid.editor, Qt.Key.Key_Return)
asked.clear()
assert shell.close_tab(shell.tabs.indexOf(w2)) and len(asked) == 1
w2b = shell.open_path(os.path.join(UD, "copy.opsheet"))
w2b.grid.begin_edit("=", True)
assert shell.close_tab(shell.tabs.indexOf(w2b))                                       # a half-typed entry never blocks closing
print("OK test_sheets_addon")
os._exit(0)
