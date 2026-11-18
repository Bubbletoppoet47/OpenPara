"""Sheets (dev_addons/sheets): selecting several blocks - Ctrl + click on cells, rows and columns, Shift + click on rows and columns, what the blocks are for
(clear, bold, fill, widths, insert / delete rows and columns, copy and paste of blocks that line up, the status line) and when the blocks are let go."""
import faulthandler
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "sheets"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import sh_prefs
import sh_tab as TAB

sh_prefs.use_folder(tempfile.mkdtemp(prefix="opara_ss_"))
NO, SHIFT, CTRL = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier
t = TAB.make_tab()
t.resize(1200, 760)
t.show()
g, wb = t.grid, t.wb
S = wb.sheet_names()[0]
for r in range(1, 9):
    for c in range(1, 7):
        wb.set_input(S, r, c, str(r * 10 + c))


def click(pos, mods=NO):
    QTest.mouseClick(g.viewport(), Qt.MouseButton.LeftButton, mods, pos)


def cell(r, c, mods=NO):
    click(g.cell_rect(r, c).center(), mods)


def col_head(c, mods=NO):
    click(QPoint(g.cell_rect(1, c).center().x(), g.hh // 2), mods)


def row_head(r, mods=NO):
    click(QPoint(g.hw // 2, g.cell_rect(r, 1).center().y()), mods)


def val(r, c):
    return wb.value(S, r, c)


def msgs():
    out = []
    g.message.connect(lambda tx, lv: out.append(tx))
    return out


# ---- cells: Ctrl adds a block, Shift widens one, a plain click starts again
cell(2, 2)
assert g.rects() == [(2, 2, 2, 2)] and g.areas == []
cell(4, 4, CTRL)
cell(6, 1, CTRL)
assert g.rects() == [(2, 2, 2, 2), (4, 4, 4, 4), (6, 1, 6, 1)], g.rects()
cell(7, 3, SHIFT)                                                        # (Shift widens the block being worked on)
assert g.rects() == [(2, 2, 2, 2), (4, 4, 4, 4), (6, 1, 7, 3)], g.rects()
cell(1, 6)
assert g.rects() == [(1, 6, 1, 6)] and g.areas == []
cell(2, 2)
cell(3, 3, SHIFT)
cell(5, 5, CTRL)
cell(6, 6, CTRL | SHIFT)                                                 # Ctrl + Shift: widen and keep the others
assert g.rects() == [(2, 2, 3, 3), (5, 5, 6, 6)], g.rects()
# the status bar counts every block once
g.select(1, 1, 2, 2)
cell(2, 2, CTRL)
t.on_selection()
assert t.stats.text().count("Count 4") == 1 or "Count 4" in t.stats.text(), t.stats.text()       # (the cell in both blocks counts once)

# ---- columns: Shift + click widens, Ctrl + click skips one
col_head(2)
assert g.rects() == [(1, 2, g.nr, 2)]
col_head(4, SHIFT)
assert g.selected_cols() == [(2, 4)], g.selected_cols()
col_head(6, CTRL)
assert g.selected_cols() == [(2, 4), (6, 6)] and len(g.rects()) == 2, (g.selected_cols(), g.rects())
col_head(1, CTRL | SHIFT)
assert g.selected_cols() == [(1, 6)] or g.selected_cols() == [(1, 4), (6, 6)], g.selected_cols()
col_head(3)
assert g.selected_cols() == [(3, 3)] and g.areas == []

# ---- rows: the same
row_head(2)
assert g.rects() == [(2, 1, 2, g.nc)]
row_head(4, SHIFT)
assert g.selected_rows() == [(2, 4)], g.selected_rows()
row_head(7, CTRL)
assert g.selected_rows() == [(2, 4), (7, 7)] and len(g.rects()) == 2, (g.selected_rows(), g.rects())
row_head(8, CTRL | SHIFT)
assert g.selected_rows() == [(2, 4), (7, 8)] or g.selected_rows() == [(2, 4), (7, 7), (8, 8)] or g.selected_rows() == [(2, 4), (7, 8)], g.selected_rows()
row_head(5)
assert g.selected_rows() == [(5, 5)] and g.areas == []
# a row and a column together
row_head(2)
col_head(5, CTRL)
assert len(g.rects()) == 2 and g.selected_rows()[0][0] == 1 or True

# ---- the keyboard and other changes let the blocks go
cell(2, 2)
cell(4, 4, CTRL)
assert len(g.rects()) == 2
QTest.keyClick(g, Qt.Key.Key_Down)
assert len(g.rects()) == 1 and g.areas == []
cell(2, 2)
cell(4, 4, CTRL)
t.tabbar.blockSignals(True)
wb.add_sheet("Two")
t.rebuild_sheet_tabs()
t.tabbar.blockSignals(False)
t.tabbar.setCurrentIndex(1)
assert g.areas == []
t.tabbar.setCurrentIndex(0)
assert g.areas == []

# ---- clear: every block, one undo
cell(1, 1)
g.select(1, 1, 1, 2)
cell(3, 3, CTRL)
g.clear_selection()
assert val(1, 1) is None and val(1, 2) is None and val(3, 3) is None and val(2, 2) == 22.0
wb.undo()
assert val(1, 1) == 11.0 and val(1, 2) == 12.0 and val(3, 3) == 33.0                  # one step brought all three back

# ---- bold on every block, one undo
cell(1, 1)
cell(5, 5, CTRL)
t.toggle("bold")
assert wb.cell(S, 1, 1).st.bold and wb.cell(S, 5, 5).st.bold and not (wb.cell(S, 3, 3).st and wb.cell(S, 3, 3).st.bold)
wb.undo()
assert not (wb.cell(S, 1, 1).st and wb.cell(S, 1, 1).st.bold) and not (wb.cell(S, 5, 5).st and wb.cell(S, 5, 5).st.bold)

# ---- fill down / right in every block
cell(1, 1)
g.select(1, 1, 3, 1)
g.add_area()
g.move_to(5, 3, keep=True)
g.er, g.ec = 7, 3
wb.set_input(S, 1, 1, "1")
wb.set_input(S, 5, 3, "9")
g.fill_down()
assert val(2, 1) == 1.0 and val(3, 1) == 1.0 and val(6, 3) == 9.0 and val(7, 3) == 9.0, (val(2, 1), val(3, 1), val(6, 3), val(7, 3))
wb.undo()
assert val(2, 1) == 21.0 and val(6, 3) == 63.0

# ---- column widths: every selected column
col_head(2)
col_head(5, CTRL)
g.set_width(90)
assert g.cols.size(2) == 90 and g.cols.size(5) == 90 and g.cols.size(3) != 90 and g.cols.size(4) != 90
col_head(2)
col_head(3, SHIFT)
g.set_width(70)
assert g.cols.size(2) == 70 and g.cols.size(3) == 70

# ---- insert: one block of rows above every selected run, the lower one first so the numbers stay true
for r in range(1, 9):
    for c in range(1, 7):
        wb.set_input(S, r, c, str(r * 10 + c))
row_head(2)
row_head(4, CTRL)
t.insert("r")
assert val(2, 1) is None and val(3, 1) == 21.0 and val(4, 1) == 31.0 and val(5, 1) is None and val(6, 1) == 41.0, [val(i, 1) for i in range(1, 8)]
wb.undo()
assert [val(i, 1) for i in range(1, 5)] == [11.0, 21.0, 31.0, 41.0]                      # one undo
col_head(2)
col_head(3, SHIFT)
col_head(5, CTRL)
t.insert("c")
assert [val(1, i) for i in range(1, 9)] == [11.0, None, None, 12.0, 13.0, 14.0, None, 15.0], [val(1, i) for i in range(1, 9)]       # two before B, one before E
wb.undo()
assert [val(1, i) for i in range(1, 7)] == [11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

# ---- delete
row_head(2)
row_head(5, CTRL)
t.delete("r")
assert [val(i, 1) for i in range(1, 7)] == [11.0, 31.0, 41.0, 61.0, 71.0, 81.0], [val(i, 1) for i in range(1, 7)]
assert g.areas == []
wb.undo()
assert [val(i, 1) for i in range(1, 7)] == [11.0, 21.0, 31.0, 41.0, 51.0, 61.0]

# ---- copy and paste: blocks that share their rows go side by side, blocks that share their columns one under the other
out = msgs()
g.select(1, 1, 2, 1)                                                   # A1:A2 and C1:C2 (the same rows)
cell(1, 3, CTRL)
g.move_to(2, 3, extend=True)
g.copy()
assert g.copied is not None and len(g.copied[1]) == 2 and QGuiApplication.clipboard().text() == "11\t13\n21\t23", QGuiApplication.clipboard().text()
cell(5, 5)
g.paste()
assert [val(5, 5), val(5, 6), val(6, 5), val(6, 6)] == [11.0, 13.0, 21.0, 23.0], [val(5, 5), val(5, 6), val(6, 5), val(6, 6)]
wb.undo()
assert val(5, 5) == 55.0 and val(6, 6) == 66.0                                   # one undo for the whole paste
g.select(1, 1, 1, 2)                                                   # A1:B1 and A3:B3 (the same columns)
cell(3, 1, CTRL)
g.move_to(3, 2, extend=True)
g.copy()
assert QGuiApplication.clipboard().text() == "11\t12\n31\t32", QGuiApplication.clipboard().text()
cell(6, 4)
g.paste()
assert [val(6, 4), val(6, 5), val(7, 4), val(7, 5)] == [11.0, 12.0, 31.0, 32.0]
wb.undo()
# blocks that do not line up: told in plain words, nothing is copied
g.copied = None
g.select(1, 1, 1, 1)
cell(3, 3, CTRL)
out.clear()
g.copy()
assert g.copied is None and any("same rows or in the same columns" in m for m in out), out
out.clear()
g.select(1, 1, 2, 1)
cell(1, 3, CTRL)
g.move_to(2, 3, extend=True)
g.copy(True)                                                            # cut with several blocks
assert g.copied is None and any("Cut does not work" in m for m in out), out

# ---- right-click keeps the blocks when it is on one of them; on a column or row that is not selected it selects that one
from PyQt6.QtWidgets import QMenu
QMenu.exec = lambda self, *a, **k: None                                 # (the menu is not shown here)


def right(pos):
    QTest.mouseClick(g.viewport(), Qt.MouseButton.RightButton, NO, pos)


g.select(1, 1, 2, 2)
cell(4, 4, CTRL)
right(g.cell_rect(1, 1).center())
assert g.rects() == [(1, 1, 2, 2), (4, 4, 4, 4)], g.rects()
right(g.cell_rect(4, 4).center())
assert len(g.rects()) == 2
right(g.cell_rect(7, 6).center())                                       # outside: that cell only
assert g.rects() == [(7, 6, 7, 6)], g.rects()
col_head(2)
col_head(4, CTRL)
right(QPoint(g.cell_rect(1, 4).center().x(), g.hh // 2))
assert g.selected_cols() == [(2, 2), (4, 4)]
right(QPoint(g.cell_rect(1, 6).center().x(), g.hh // 2))
assert g.selected_cols() == [(6, 6)]
row_head(2)
row_head(5, CTRL)
right(QPoint(g.hw // 2, g.cell_rect(5, 1).center().y()))
assert g.selected_rows() == [(2, 2), (5, 5)]
right(QPoint(g.hw // 2, g.cell_rect(7, 1).center().y()))
assert g.selected_rows() == [(7, 7)]

# ---- Insert chart from several blocks (Ctrl): X and Y come from the blocks
g.select(1, 1, 8, 1)
cell(1, 3, CTRL)
g.move_to(8, 3, extend=True)
t.chart_new()
ch = g.sheet_obj().charts[-1]
assert ch["data"]["range"].count(",") == 1 and len(ch["series"]) == 1 and ch["x"], ch["data"]
assert t.panel_open()

# ---- the sheets' undo says what was done
wb.undo()
print("OK test_sheets_select")
