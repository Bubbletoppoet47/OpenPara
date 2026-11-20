"""Sheets (dev_addons/sheets): the window - typing and the formula bar, point-and-click references (across sheets), the name box, sheet tabs, the ribbon, the
standards window and the Function Arguments window, charts from the grid, study import / refresh, .opsheet and .xlsx files, the one-time openpyxl download."""
import faulthandler
import json
import os
import shutil
import sys
import tempfile

faulthandler.dump_traceback_later(175, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

app = QApplication([])
import sh_book as B
import sh_deps
import sh_dialogs as D
import sh_tab as TAB

T = tempfile.mkdtemp(prefix="opara_st_")
S = "Sheet1"
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
answers = {"question": YES, "save": None, "open": None, "text": None, "item": None}
QMessageBox.question = staticmethod(lambda *a, **k: answers["question"])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (answers["save"] or "", ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (answers["open"] or "", ""))
QInputDialog.getText = staticmethod(lambda *a, **k: (answers["text"], answers["text"] is not None))
QInputDialog.getInt = staticmethod(lambda *a, **k: (answers["int"], True))


def fresh():
    t = TAB.make_tab()
    t.resize(1100, 720)
    t.show()
    app.processEvents()
    return t


def typ(t, text, key=Qt.Key.Key_Return):
    g = t.grid
    QTest.keyClicks(g, text[0])
    if len(text) > 1:
        QTest.keyClicks(g.editor, text[1:])
    QTest.keyClick(g.editor, key)


def click(t, r, c, mod=Qt.KeyboardModifier.NoModifier):
    g = t.grid
    QTest.mouseClick(g.viewport(), Qt.MouseButton.LeftButton, mod, g.cell_rect(r, c).center())


def val(t, r, c, sheet=None):
    return t.wb.value(sheet or S, r, c)                                       # S is the name of the first sheet (it changes when the test renames it)


def close(a, b, tol=1e-9):
    return isinstance(a, float) and abs(a - b) <= tol * max(1.0, abs(b))


# ================================================================ the window
t = fresh()
g, wb = t.grid, t.wb
assert [t.ribbon.tabText(i) for i in range(t.ribbon.count())] == ["Home", "Data", "Charts", "Media", "Import", "Engineering", "View"]
assert t.title() == "Sheets" and not t.is_dirty() and t.can_close()
std_buttons = [k for k in t.act if k.startswith("std_")]
assert "std_aisi-s100-16" in std_buttons and "std_select" in std_buttons
b = t.act["std_aisi-s100-16"]
assert "AISI" in b.text().replace("\n", " ") and "North American Specification" in b.toolTip() and "2016" in b.toolTip()
for key in ("new", "open", "save", "save_as", "paste", "bold", "italic", "dec_up", "dec_dn", "ins_row", "del_col", "fill_down", "undo", "redo", "study_in", "study_refresh", "xl_in",
            "xl_out", "names", "sh_add", "sh_paste", "ch_new", "ch_edit", "ch_export", "fx", "std_select"):
    assert key in t.act and t.act[key].toolTip(), key
assert not t.act["undo"].isEnabled() and not t.act["study_refresh"].isEnabled() and not t.act["ch_edit"].isEnabled() and not t.act["sh_del"].isEnabled()

# ---- typing, Enter moves down, formulas, the formula bar follows, dirty marks
typ(t, "5")
typ(t, "=A1*2")
typ(t, "=SUM(A1:A2)")
assert [val(t, r, 1) for r in (1, 2, 3)] == [5.0, 10.0, 15.0] and (g.r, g.c) == (4, 1)
assert t.is_dirty() and t.title_lbl.text().endswith("*") and t.act["undo"].isEnabled()
g.select(2, 1)
assert t.bar.text() == "=A1*2" and t.name_box.text() == "A2"
g.select(1, 1, 3, 2)
assert t.name_box.text() == "A1:B3" and "Sum 30" in t.stats.text() and "Count 3" in t.stats.text(), t.stats.text()

# ---- the formula bar edits the active cell (a click in it starts the edit, the cursor stays where it was clicked)
g.select(2, 1)
t.bar.hasFocus = lambda: True
t.bar.setCursorPosition(3)
t.start_bar_edit()
assert g.edit is not None and t.bar.cursorPosition() == 3
t.bar.setText("=A1*4")
QTest.keyClicks(t.bar, "")
t.bar.textEdited.emit("=A1*4")
QTest.keyClick(t.bar, Qt.Key.Key_Return)
assert g.edit is None and val(t, 2, 1) == 20.0 and val(t, 3, 1) == 25.0
del t.bar.hasFocus
g.select(2, 1)
g.begin_edit("=A1*9", True)
QTest.keyClick(g.editor, Qt.Key.Key_Escape)                                     # Esc leaves the cell as it was
assert g.edit is None and wb.cell(S, 2, 1).raw == "=A1*4"
g.begin_edit("=((", True)
assert g.commit_edit() is False and g.edit is not None                          # a formula that cannot be read stays open, with a plain message
assert "cannot be read" in t.status.text()
g.cancel_edit()

# ---- point and click: a click on a cell puts its address in the formula; a click on another sheet's tab continues there with the sheet's name
t.add_sheet()
assert wb.sheet_names() == [S, "Sheet2"] and g.sheet == "Sheet2" and t.tabbar.count() == 2
g.select(1, 1)
QTest.keyClicks(g, "=")
t.tabbar.setCurrentIndex(0)                                                     # while a formula is being typed the sheet tab only changes what is shown
assert g.edit is not None and g.sheet == "Sheet1"
click(t, 2, 1)
assert g.editor_for_point().text() == "=Sheet1!A2", g.editor_for_point().text()
QTest.keyClicks(g.editor_for_point(), "*2")
QTest.keyClick(g.editor_for_point(), Qt.Key.Key_Return)
assert g.sheet == "Sheet2" and wb.cell("Sheet2", 1, 1).raw == "=Sheet1!A2*2" and val(t, 1, 1, "Sheet2") == 40.0
assert t.tabbar.currentIndex() == 1                                              # the tab strip followed the grid back to the sheet that was being typed on
t.tabbar.setCurrentIndex(0)
assert g.sheet == "Sheet1" and t.name_box.text() == "A2"
g.select(4, 4)
QTest.keyClicks(g, "=")
click(t, 1, 1)
QTest.keyClicks(g.editor, "+")
click(t, 2, 1, Qt.KeyboardModifier.NoModifier)
assert g.editor.text() == "=A1+A2"                                              # same sheet: no sheet name
QTest.keyClick(g.editor, Qt.Key.Key_Return)
assert val(t, 4, 4) == 25.0

# ---- the name box: a cell, a range, a name for the selection (this sheet only), jumping to a name, a bad name
t.name_box.setText("C5")
t.name_entered()
assert (g.r, g.c) == (5, 3) and g.sel() == (5, 3, 5, 3)
t.name_box.setText("A1:B3")
t.name_entered()
assert g.sel() == (1, 1, 3, 2)
g.select(4, 2)
t.name_box.setText("NumScrews")
t.name_entered()
assert g.sheet_obj().names == {"NumScrews": "=Sheet1!$B$4"}
wb.set_input(S, 4, 2, "12")
typ_cell = (6, 6)
g.select(*typ_cell)
typ(t, "=NumScrews*2")
assert val(t, 6, 6) == 24.0
g.select(9, 9)
t.name_box.setText("numscrews")
t.name_entered()
assert (g.r, g.c) == (4, 2)                                                       # jumps there (names ignore capitals)
t.name_box.setText("1bad")
t.name_entered()
assert "not a cell" in t.status.text()
t.name_box.setText("Sheet2!B2:C3")                                                 # a range on another sheet shows that sheet
t.name_entered()
assert g.sheet == "Sheet2" and g.sel() == (2, 2, 3, 3)
t.tabbar.setCurrentIndex(0)

# ---- sheet tabs: rename (formulas that read it follow), copy, move, delete, the last one stays
answers["text"] = "My Data"
t.rename_sheet(1)
assert wb.sheet_names() == [S, "My Data"] and wb.cell("My Data", 1, 1).raw == "=Sheet1!A2*2"
t.rename_sheet(0)                                                                 # renaming Sheet1 to "My Data" again is refused
assert wb.sheet_names() == [S, "My Data"] and "cannot be used" in t.status.text()
answers["text"] = "Loads"
t.rename_sheet(0)
assert wb.sheet_names() == ["Loads", "My Data"] and wb.cell("My Data", 1, 1).raw == "=Loads!A2*2" and g.sheet == "Loads"
S = "Loads"
t.duplicate_sheet()
assert len(wb.sheet_names()) == 3 and g.sheet != "Loads" and t.tabbar.count() == 3
t.tabbar.moveTab(wb.sheet_names().index(g.sheet), 0)                              # dragging a tab moves the sheet
assert wb.sheet_names()[0] == g.sheet and t.tabbar.tabText(0) == wb.sheet_names()[0]
dup = g.sheet
answers["question"] = NO
t.delete_sheet(t.tabbar.currentIndex())
assert dup in wb.sheet_names()
answers["question"] = YES
t.delete_sheet(t.tabbar.currentIndex())
assert dup not in wb.sheet_names() and t.tabbar.count() == 2 and g.sheet in wb.sheet_names()
t.tabbar.setCurrentIndex(wb.sheet_names().index("My Data"))
t.delete_sheet(t.tabbar.currentIndex())
assert wb.sheet_names() == ["Loads"] and not t.act["sh_del"].isEnabled()
t.delete_sheet(0)
assert wb.sheet_names() == ["Loads"] and "at least one" in t.status.text()
wb.undo()
assert "My Data" in wb.sheet_names() and t.tabbar.count() == 2
t.tabbar.setCurrentIndex(wb.sheet_names().index("Loads"))

# ---- the ribbon: bold / italic follow the cell, number formats, decimals, insert / delete, fill, clear, undo / redo
g.select(1, 1)
t.act["bold"].click()
assert wb.cell(S, 1, 1).st.bold and t.act["bold"].isChecked()
g.select(2, 1)
assert not t.act["bold"].isChecked()
g.select(1, 1)
t.act["bold"].click()
assert not (wb.cell(S, 1, 1).st and wb.cell(S, 1, 1).st.bold)
g.select(2, 1, 3, 1)
t.set_format("0.00")
assert wb.display(S, 2, 1) == "20.00"
t.decimals(1)
assert wb.display(S, 2, 1) == "20.000"
t.decimals(-1)
t.decimals(-1)
assert wb.display(S, 2, 1) == "20.0"
t.set_format("0%")
assert wb.display(S, 2, 1) == "2000%"
t.set_format("General")
g.select(1, 5)
wb.set_input(S, 1, 5, "7")
g.select(1, 5, 4, 5)
t.act["fill_down"].click()
assert [val(t, r, 5) for r in range(1, 5)] == [7.0] * 4
g.select(1, 5, 1, 7)
t.act["fill_right"].click()
assert val(t, 1, 7) == 7.0
g.select(1, 5, 4, 7)
t.act["clear"].click()
assert wb.cell(S, 1, 5) is None or wb.cell(S, 1, 5).raw is None
t.act["undo"].click()
assert val(t, 1, 5) == 7.0 and t.act["redo"].isEnabled()
t.act["redo"].click()
n_before = val(t, 3, 1)
g.select(2, 1)
t.act["ins_row"].click()
assert wb.cell(S, 3, 1).raw == "=A1*4" and wb.cell(S, 4, 1).raw == "=SUM(A1:A3)"
assert val(t, 4, 1) == n_before
t.act["del_row"].click()
assert wb.cell(S, 3, 1).raw.startswith("=SUM(")
g.select(1, 1)
answers["int"] = 150
t.col_width()
assert g.cols.size(1) == 150

# ---- copy / paste special (values only)
g.select(3, 1)
g.copy()
g.select(8, 8)
D.PasteSpecialDialog.exec = lambda self: True
D.PasteSpecialDialog.what = lambda self: "values"
t.paste_special()
assert wb.cell(S, 8, 8).raw == val(t, 3, 1) and not isinstance(wb.cell(S, 8, 8).raw, str)

# ---- the standards window -> Function Arguments -> a formula in the cell
shown = []


class AutoBrowser(D.StandardsBrowser):
    """The real window, driven the way a person would: search, pick the first match, press Insert into cell."""
    query = "pull-out"

    def exec(self):
        self.search.setText(self.query)
        assert self.current_func() is not None and self.current_func().full_name == "AISI16.J4_4_1", self.status.text()
        assert self.b_insert.isEnabled()
        assert self.tree.topLevelItemCount() == 1 and "AISI S100-16" in self.tree.topLevelItem(0).text(0)
        shown.append(self.current_func().full_name)
        self.insert()
        return True


D.StandardsBrowser = AutoBrowser
TAB.D.StandardsBrowser = AutoBrowser
g.select(10, 2)
t.standards("aisi-s100-16")
dlg = t.dialogs[-1]
assert isinstance(dlg, D.FunctionArgsDialog) and dlg.func.name == "AISI16.J4_4_1" and shown == ["AISI16.J4_4_1"]
assert [r[0].text() for r in dlg.rows][:3] == ["tc", "d", "Fu2"] and dlg.formula() == "=AISI16.J4_4_1()"
assert "Still needed" in dlg.warn.text()
for i, txt in enumerate(["0.0747", "0.1875", "58000"]):
    dlg.rows[i][1].setText(txt)
assert dlg.formula() == "=AISI16.J4_4_1(0.0747, 0.1875, 58000)" and "690.508" in dlg.result.text(), dlg.result.text()
assert dlg.rows[0][3].text() == "= 0.0747"
dlg.ok()
assert wb.cell(S, 10, 2).raw == "=AISI16.J4_4_1(0.0747, 0.1875, 58000)" and close(val(t, 10, 2), 690.508125)
assert dlg not in t.dialogs or not dlg.isVisible()
# fx on that cell opens the same window with the values in it; changing one and OK rewrites the formula
g.select(10, 2)
t.fx()
d2 = t.dialogs[-1]
assert d2.func.name == "AISI16.J4_4_1" and [x for x in d2.texts()] == ["0.0747", "0.1875", "58000"]
d2.rows[2][1].setText("A1*0+60000")
d2.rows[3][1].setEditText("ASD")
assert close(wb.evaluate(d2.formula(), S), 0.85 * 0.0747 * 0.1875 * 60000 / 3.0), d2.formula()
d2.ok()
assert wb.cell(S, 10, 2).raw.endswith(', "ASD")'), wb.cell(S, 10, 2).raw
assert close(val(t, 10, 2), 0.85 * 0.0747 * 0.1875 * 60000 / 3.0)
# a warning of the standard shows on the cell, in the help line, and a triangle is kept for the grid
g.select(11, 2)
typ(t, "=AISI16.J4_4_2(0.058,0.2,70000)")
g.select(11, 2)
assert wb.warnings.get((S, 11, 2)) and t.help.text().startswith("⚠") and "5/16" in t.help.text()
# the function picker for an empty cell, then the arguments window for SUM with a range picked from the grid
g.select(13, 2)


class AutoPicker(D.FunctionPicker):
    def exec(self):
        self.chosen = "SUM"
        return True


D.FunctionPicker = AutoPicker
TAB.D.FunctionPicker = AutoPicker
t.fx()
d3 = t.dialogs[-1]
assert d3.func.name == "SUM" and d3.variadic
d3.rows[0][1].setText("A1:A3")
assert d3.formula() == "=SUM(A1:A3)"
d3.ok()
assert wb.cell(S, 13, 2).raw == "=SUM(A1:A3)"
# while a formula is being typed the window writes into the editor, not the cell
g.select(14, 2)
QTest.keyClicks(g, "=")
t.fx()
d4 = t.dialogs[-1]
d4.rows[0][1].setText("1")
d4.rows[1][1].setText("2")
d4.ok()
assert g.edit is not None and g.edit_text_now() == "=SUM(1, 2)", g.edit_text_now()
QTest.keyClick(g.editor, Qt.Key.Key_Return)
assert val(t, 14, 2) == 3.0
for d in list(t.dialogs):
    d.close()

# ---- the help line: the function being typed with the argument under the cursor in bold
g.select(16, 2)
g.begin_edit("=AISI16.J4_4_1(0.0747,", True)
t.update_help()
assert "AISI16.J4_4_1(" in t.help.text() and "<b>d</b>" in t.help.text(), t.help.text()
g.cancel_edit()
assert t.help.text() == ""

# ---- charts: from the selection, a single cell takes the block around it, edit window, export, copy, delete
t2 = fresh()
g2 = t2.grid
sheet2 = t2.wb.sheet_names()[0]
for i in range(1, 7):
    t2.wb.set_input(sheet2, i, 1, str(i))
for i in range(1, 7):
    t2.wb.set_input(sheet2, i, 2, f"=A{i}^2")
    t2.wb.set_input(sheet2, i, 3, f"=A{i}*100")
g2.select(3, 2)                                                                       # one cell: Excel takes the block around it
t2.chart_new()
ch = g2.sheet_obj().charts[0]
assert ch["x"] == f"{sheet2}!A1:A6" and len(ch["series"]) == 2 and len(g2.frames) == 1 and t2.act["ch_edit"].isEnabled()
t2.chart_new()
assert len(g2.sheet_obj().charts) == 2 and g2.sheet_obj().charts[1]["id"] != ch["id"]
t2.chart_copy(ch["id"])
assert len(g2.sheet_obj().charts) == 3
t2.chart_edit(ch["id"])                                                                 # the panel on the right opens for the chart
assert t2.panel_open() and t2.panel.chart is ch and not t2.panel.isHidden() and t2.panel.heading.text().startswith("Chart")
assert t2.panel.data_range.text() == ch["data"]["range"] and len(t2.panel.rows) == 2 and t2.panel.xrange.text() == ch["x"]
for f in g2.frames.values():
    f.redraw()
app.processEvents()
png = os.path.join(T, "c.png")
answers["save"] = png
t2.chart_export(ch["id"])
assert open(png, "rb").read(4) == b"\x89PNG" and "Saved" in t2.status.text()
answers["save"] = os.path.join(T, "c")                                                # no ending: PNG is added
t2.chart_export(ch["id"])
assert os.path.isfile(os.path.join(T, "c.png"))
t2.grid.pick_chart(ch["id"])
t2.chart_delete()
assert len(g2.sheet_obj().charts) == 2 and ch["id"] not in g2.frames
g2.select(20, 20)
for c_ in list(g2.sheet_obj().charts):
    g2.delete_chart(c_["id"])
t2.chart_new()                                                                        # nothing to plot: an empty chart, and the panel waits for cells
assert len(g2.sheet_obj().charts) == 1 and g2.sheet_obj().charts[0]["series"] == [] and t2.panel_open() and t2.panel.picking()
assert "Select its cells" in t2.status.text()
for d in list(t2.dialogs):
    d.close()

# ---- study import and refresh


def write_study(project, n, extra=False):
    root = os.path.join(project, "study")
    os.makedirs(root, exist_ok=True)
    outs = [["smax", "Max stress (psi)"], ["d", "Defl (in)"]] + ([["w", "Weight (lb)"]] if extra else [])
    cases = [{"label": i + 1, "values": {"t": f"{0.05 + 0.01 * i:.12g}"}, "status": "ok", "outputs": {"smax": 1000.0 + 12.5 * i, "d": 0.1 * i, "w": 5.0 + i}} for i in range(n)]
    json.dump({"format": "openpara-study", "version": 1, "checked": ["t"], "rows": [{}], "outputs": [o[0] for o in outs], "exit_conds": [], "cases": cases,
               "run_meta": {"params": [["t", "Thickness (in)"]], "outputs": outs, "unit": None}}, open(os.path.join(root, "study.json"), "w"))


class FakeStudyTab:
    kind = "study"

    def __init__(self, path):
        self.sw = type("SW", (), {"path": path})()


class FakeTabs:
    def __init__(self, ws):
        self.ws = ws

    def count(self):
        return len(self.ws)

    def widget(self, i):
        return self.ws[i]


proj = os.path.join(T, "truss")
write_study(proj, 4)
t3 = fresh()
t3.host = type("Host", (), {"tabs": FakeTabs([FakeStudyTab(proj), FakeStudyTab(os.path.join(T, "nostudy")), object()])})()
assert t3.open_study_projects() == [("truss", proj)]                                   # only open study tabs that hold a study
link = t3.study_import((proj, "", True))
g3 = t3.grid
assert link["rows"] == 4 and g3.sheet == "Study" and t3.wb.sheet_names() == ["Sheet1", "Study"] and g3.sel() == (1, 1, 5, 5)
assert t3.wb.value("Study", 1, 2) == "Thickness (in)" and t3.act["study_refresh"].isEnabled()
t3.wb.set_input("Study", 1, 6, "Ratio")
for r in range(2, 6):
    t3.wb.set_input("Study", r, 6, f"=D{r}/5000")
g3.select(3, 3)
t3.update_help()
assert "Imported from truss - Study 1" in t3.help.text()
write_study(proj, 7)
os.utime(os.path.join(proj, "study", "study.json"), (os.path.getmtime(os.path.join(proj, "study", "study.json")) + 9,) * 2)
t3.update_help()
assert "newer results" in t3.help.text()
assert t3.study_refresh() is not None
assert t3.wb.get_sheet("Study").links[0]["rows"] == 7 and t3.wb.cell("Study", 8, 6).raw == "=D8/5000" and close(t3.wb.value("Study", 8, 6), 1075.0 / 5000)
t3.update_help()
assert "newer results" not in t3.help.text() and "Study 1" in t3.help.text()
t3.act["undo"].click()                                                                 # Refresh is one undo step
assert t3.wb.get_sheet("Study").links[0]["rows"] == 4 and t3.wb.cell("Study", 8, 6) is None
t3.act["redo"].click()
t3.wb.set_input("Study", 9, 2, "mine")                                                 # under the block: a refresh that grows asks first
write_study(proj, 9)
os.utime(os.path.join(proj, "study", "study.json"), (os.path.getmtime(os.path.join(proj, "study", "study.json")) + 20,) * 2)
answers["question"] = NO
assert t3.study_refresh() is None and t3.wb.value("Study", 9, 2) == "mine" and t3.wb.get_sheet("Study").links[0]["rows"] == 7
answers["question"] = YES
assert t3.study_refresh() is not None and t3.wb.get_sheet("Study").links[0]["rows"] == 9 and t3.wb.value("Study", 9, 2) != "mine"
t3.tabbar.setCurrentIndex(0)
assert t3.study_refresh() is None and "no imported study" in t3.status.text()
t3.study_import((os.path.join(T, "nostudy"), "", False))
assert "could not be read" in t3.status.text() and t3.wb.get_sheet("Sheet1").links == []
# the import window itself: a project that is open, a sub-study, the answer as (project, sub, new sheet)
dlg = D.StudyImportDialog([("truss", proj)])
assert dlg.result_choice()[0] == proj and dlg.result_choice()[1] == ""

# ---- files: Save as, Save, reopen; the title, the star, can_close; Ctrl+S
t4 = fresh()
typ(t4, "3")
typ(t4, "=A1^2")
t4.wb.add_sheet("Other")
t4.wb.set_input("Other", 1, 1, "=Sheet1!A2+1")
f = os.path.join(T, "book")
answers["save"] = f
assert t4.save(True) and t4.path == f + ".opsheet" and t4.title() == "book.opsheet" and not t4.is_dirty() and os.path.isfile(f + ".opsheet")
typ(t4, "4")
assert t4.is_dirty()
QTest.keyClick(t4, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
assert not t4.is_dirty() and B.Workbook.load(f + ".opsheet").value("Sheet1", 3, 1) == 4.0
g4 = t4.grid
t5 = TAB.make_tab(f + ".opsheet")
assert t5.path == f + ".opsheet" and t5.wb.value("Other", 1, 1) == 10.0 and not t5.is_dirty() and t5.wb.sheet_names() == ["Sheet1", "Other"]
g4.set_sheet("Other")
t4.grid.begin_edit("=", True)
assert t4.can_close() is True                                                          # an edit in progress is finished first (here: "=" alone is text)
open(os.path.join(T, "broken.opsheet"), "w").write("{nope")
t6 = TAB.make_tab()
assert t6.open_path(os.path.join(T, "broken.opsheet")) is False and "Couldn't open" in t6.status.text() and not t6.is_dirty()
assert t6.open_path(os.path.join(T, "missing.opsheet")) is False

# ---- Excel files: open, title, export, and the one-time download of openpyxl when it is missing
op = sh_deps.openpyxl()
if op is not None:
    wx = op.Workbook()
    ws = wx.active
    ws.title = "Loads"
    ws["A1"], ws["A2"], ws["B1"] = 4, 6, "=SUM(A1:A2)"
    xl = os.path.join(T, "loads.xlsx")
    wx.save(xl)
    t7 = fresh()
    assert t7.open_path(xl) and t7.title() == "loads.xlsx" and t7.path is None and t7.wb.value("Loads", 1, 2) == 10.0 and not t7.is_dirty()
    assert t7.wb.sheet_names() == ["Loads"] and t7.grid.sheet == "Loads"
    out = os.path.join(T, "out.xlsx")
    notes = t7.export_xlsx(out)
    assert notes is not None and op.load_workbook(out)["Loads"]["B1"].value == "=SUM(A1:A2)"
    answers["save"] = os.path.join(T, "named")
    answers["open"] = xl
    t7.import_xlsx_dialog()                                                            # a second workbook in the same tab: it opens in a new tab if there is a host
    t7.export_xlsx_dialog()
    assert os.path.isfile(os.path.join(T, "named.xlsx"))

    real = sh_deps.openpyxl
    calls = []

    def fake_installer(pins, target, progress):
        calls.append(pins)
        pkg_root = os.path.dirname(os.path.dirname(op.__file__))
        for name in ("openpyxl", "et_xmlfile"):
            shutil.copytree(os.path.join(pkg_root, name), os.path.join(target, name))

    sh_deps.openpyxl = lambda: real() if calls else None
    TAB.sh_deps.openpyxl = sh_deps.openpyxl
    try:
        t8 = fresh()
        t8.AUTO_DOWNLOAD = False
        assert t8.open_path(xl) is False and "openpyxl is needed" in t8.status.text() and not calls
        t8.AUTO_DOWNLOAD = True
        answers["question"] = NO
        assert t8.open_path(xl) is False and not calls                                 # asked first; "No" downloads nothing
        answers["question"] = YES
        t8.installer = fake_installer
        assert t8.open_path(xl) is True and len(calls) == 1 and t8.wb.value("Loads", 1, 2) == 10.0, t8.status.text()
        assert os.path.isdir(sh_deps.site_dir())
        t8.export_xlsx(os.path.join(T, "second.xlsx"))
        assert len(calls) == 1                                                         # once only
        t9 = fresh()
        t9.installer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no internet connection"))
        shutil.rmtree(sh_deps.site_dir(), ignore_errors=True)
        calls.clear()
        assert t9.open_path(xl) is False and t9.path is None
    finally:
        sh_deps.openpyxl = real
        TAB.sh_deps.openpyxl = real
else:
    print("openpyxl is not available here: the Excel parts of the window test are skipped")

# ---- closing: dialogs close, an edit in progress is dropped, nothing raises
t10 = fresh()
d = t10.open_args("SUM", None)
t10.grid.begin_edit("=1+", True)
t10.shutdown()
assert not d.isVisible() and t10.grid.edit is None

print("OK test_sheets_tab")
os._exit(0)
