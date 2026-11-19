"""Sheets (dev_addons/sheets), with real mouse drags and key presses: F4 in the cell editor and the formula bar; the fill handle shows where it will fill and with what
before the button is let go; a selection is dragged by its border to move (Ctrl: copy) and the formulas and charts that point at it follow."""
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
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
import sh_chart as C
import sh_prefs
import sh_tab as TAB

sh_prefs.use_folder(tempfile.mkdtemp(prefix="opara_ss_"))
NO, CTRL = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier
LEFT = Qt.MouseButton.LeftButton
t = TAB.make_tab()
t.resize(1200, 760)
t.show()
g, wb = t.grid, t.wb
S = wb.sheet_names()[0]
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(a[2] if len(a) > 2 else ""), answer[0])[1])
answer = [QMessageBox.StandardButton.Yes]


def raw(r, c):
    cell = wb.cell(S, r, c)
    return None if cell is None else cell.raw


def val(r, c):
    return wb.value(S, r, c)


def cell(r, c, mods=NO):
    QTest.mouseClick(g.viewport(), LEFT, mods, g.cell_rect(r, c).center())


def drag(p0, p1, mods=NO, steps=4):
    """Press at p0, move to p1 in a few steps (the drag state is read at every step), release."""
    QTest.mousePress(g.viewport(), LEFT, mods, p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(g.viewport(), QPoint(p0.x() + (p1.x() - p0.x()) * i // steps, p0.y() + (p1.y() - p0.y()) * i // steps))
    QTest.mouseRelease(g.viewport(), LEFT, mods, p1)


def border_left(r1, c1, r2, c2):
    rc = g.block_rect(r1, c1, r2, c2)
    return QPoint(rc.left() + 1, (rc.top() + rc.bottom()) // 2)


def paint_ok():
    """The drag overlay paints without an error (an error in painting is only logged, so call it directly)."""
    img = QImage(g.viewport().size(), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    g._paint_drag(p, None)
    p.end()
    g.viewport().grab()


# ---------------------------------------------------------------- F4 in the cell editor and in the formula bar
wb.set_input(S, 1, 1, "5")
cell(3, 3)
g.begin_edit(None, enter_mode=False)
g.editor.setText("=A1+B2")
g.editor.setCursorPosition(3)                                           # right after A1
QTest.keyClick(g.editor, Qt.Key.Key_F4)
assert g.editor.text() == "=$A$1+B2", g.editor.text()
QTest.keyClick(g.editor, Qt.Key.Key_F4)
assert g.editor.text() == "=A$1+B2"
QTest.keyClick(g.editor, Qt.Key.Key_F4)
assert g.editor.text() == "=$A1+B2"
QTest.keyClick(g.editor, Qt.Key.Key_F4)
assert g.editor.text() == "=A1+B2" and g.editor.cursorPosition() == 3
g.editor.setCursorPosition(len(g.editor.text()))
QTest.keyClick(g.editor, Qt.Key.Key_F4)                                  # the cursor at the end of the last reference
assert g.editor.text() == "=A1+$B$2"
g.editor.selectAll()
QTest.keyClick(g.editor, Qt.Key.Key_F4)                                  # a selection: every reference in it, from the first one's state
assert g.editor.text() == "=$A$1+$B$2", g.editor.text()
QTest.keyClick(g.editor, Qt.Key.Key_Escape)
assert not g.editor.isVisible()
t.bar.setText("=SUM(A1:B2)")
t.bar.setCursorPosition(7)
QTest.keyClick(t.bar, Qt.Key.Key_F4)
assert t.bar.text() == "=SUM($A$1:$B$2)", t.bar.text()
t.bar.setText("")

# ---------------------------------------------------------------- the fill handle: the outline and the values before the button is let go
for r in range(1, 9):
    for c in range(1, 7):
        wb.set_input(S, r, c, str(r * 10 + c))
wb.set_input(S, 1, 8, "=A1*2")
wb.set_input(S, 2, 8, "=A2*2")
g.select(1, 1, 2, 1)                                                     # A1:A2 = 11, 21: a series
rc = g.block_rect(1, 1, 2, 1)
handle = QPoint(rc.right() - 2, rc.bottom() - 2)
QTest.mousePress(g.viewport(), LEFT, NO, handle)
assert g._drag and g._drag[0] == "fill"
QTest.mouseMove(g.viewport(), g.cell_rect(5, 1).center())
assert g._fill_target((1, 1, 2, 1), g._last_cursor) == (3, 1, 5, 1)
prev = wb.fill_preview(S, (1, 1, 2, 1), (3, 1, 5, 1))
assert {k: v[0] for k, v in prev.items()} == {(3, 1): "31", (4, 1): "41", (5, 1): "51"} and all(v[1] for v in prev.values()), prev
assert raw(3, 1) == 31.0 and raw(5, 1) == 51.0, "nothing is changed by the preview"
orig_a = [raw(r, 1) for r in range(1, 9)]
paint_ok()
QTest.mouseMove(g.viewport(), g.cell_rect(7, 1).center())
assert g._fill_target((1, 1, 2, 1), g._last_cursor) == (3, 1, 7, 1)
paint_ok()
QTest.mouseRelease(g.viewport(), LEFT, NO, g.cell_rect(7, 1).center())
assert [raw(r, 1) for r in range(1, 8)] == [11.0, 21.0, 31.0, 41.0, 51.0, 61.0, 71.0], [raw(r, 1) for r in range(1, 8)]
wb.undo()
assert [raw(r, 1) for r in range(1, 9)] == orig_a
# formulas: shown as the value they will have, locked references stay
wb.set_input(S, 1, 9, "=$A$1+A1")
wb.set_input(S, 2, 9, "=$A$1+A2")
pv = wb.fill_preview(S, (1, 9, 2, 9), (3, 9, 4, 9))
assert pv[(3, 9)][0] == "42", pv                                          # $A$1 (11) + A3 (31)
assert raw(3, 9) is None
pv = wb.fill_preview(S, (1, 8, 2, 8), (3, 8, 3, 8))
assert pv[(3, 8)][0] == "62", pv                                            # A3 * 2
# a formula in the filled area reads the cells as they will be after the fill, not as they are now
wb.set_input(S, 30, 1, "5"); wb.set_input(S, 31, 1, "=A30*2"); wb.set_input(S, 30, 2, "100"); wb.set_input(S, 31, 2, "7")
pv = wb.fill_preview(S, (30, 1, 31, 1), (30, 2, 31, 3))
assert pv[(30, 2)][0] == "5" and pv[(31, 2)][0] == "10" and pv[(31, 3)][0] == "10", pv
assert raw(30, 2) == 100.0 and raw(31, 2) == 7.0 and wb.value(S, 30, 2) == 100.0, "and nothing was changed"
# no preview when the mouse is not past the block
assert g._fill_target((1, 1, 2, 1), g.cell_rect(2, 1).center()) is None

# ---------------------------------------------------------------- drag a selection by its border to move it
wb.set_input(S, 20, 1, "=B2+B3")                                         # points at the block
wb.set_input(S, 21, 1, "=SUM(B2:B3)")
ch = C.from_selection(wb, S, (2, 1, 3, 2), ())
wb.get_sheet(S).charts.append(ch)
g.select(2, 2, 3, 2)                                                     # B2:B3 = 22, 32
n_undo = len(wb._undo)
p0 = border_left(2, 2, 3, 2)
assert g._on_border(p0) and not g._on_border(g.cell_rect(2, 2).center()), "the border, not the inside"
QTest.mousePress(g.viewport(), LEFT, NO, p0)
assert g._drag[0] == "move"
QTest.mouseMove(g.viewport(), QPoint(g.cell_rect(12, 5).center().x() - (g.cell_rect(2, 2).center().x() - p0.x()), g.cell_rect(12, 5).center().y()))
paint_ok()
assert g._moved_to is not None
QTest.mouseRelease(g.viewport(), LEFT, NO, QPoint(g.cell_rect(12, 5).center().x() - (g.cell_rect(2, 2).center().x() - p0.x()), g.cell_rect(12, 5).center().y()))
tr, tc = g.sel()[0], g.sel()[1]
assert (raw(tr, tc), raw(tr + 1, tc)) == (22.0, 32.0) and raw(2, 2) is None and raw(3, 2) is None, (g.sel(), raw(tr, tc))
a = f"{TAB.E.addr(tr, tc)}"
assert raw(20, 1) == f"={TAB.E.addr(tr, tc)}+{TAB.E.addr(tr + 1, tc)}" and raw(21, 1) == f"=SUM({a}:{TAB.E.addr(tr + 1, tc)})", (raw(20, 1), raw(21, 1))
assert val(20, 1) == 54.0 and val(21, 1) == 54.0
assert wb.get_sheet(S).charts[0]["data"]["range"] == f"Sheet1!A2:A3, Sheet1!{TAB.E.addr(tr, tc)}:{TAB.E.addr(tr + 1, tc)}", wb.get_sheet(S).charts[0]["data"]   # split at the block's edge
ser = wb.get_sheet(S).charts[0]["series"][0]["y"]
assert ser == f"Sheet1!{TAB.E.addr(tr, tc)}:{TAB.E.addr(tr + 1, tc)}", ser                       # the chart's Y range moved with the cells
assert wb.get_sheet(S).charts[0]["x"] == "Sheet1!A2:A3", "its X range was not in the block"
assert len(wb._undo) == n_undo + 1, "one undo step for the whole move"
wb.undo()
assert raw(2, 2) == 22.0 and raw(3, 2) == 32.0 and raw(tr, tc) is None and raw(20, 1) == "=B2+B3"
assert wb.get_sheet(S).charts[0]["series"][0]["y"] == "Sheet1!B2:B3" and wb.get_sheet(S).charts[0]["data"]["range"] == "Sheet1!A2:B3"

# Ctrl: copy (the original stays, formulas that point at it stay)
g.select(2, 2, 3, 2)
p0 = border_left(2, 2, 3, 2)
dst = QPoint(g.cell_rect(12, 5).center().x() - (g.cell_rect(2, 2).center().x() - p0.x()), g.cell_rect(12, 5).center().y())
drag(p0, dst, CTRL)
assert raw(2, 2) == 22.0 and raw(3, 2) == 32.0 and raw(12, 5) == 22.0 and raw(13, 5) == 32.0, (raw(2, 2), raw(12, 5))
assert raw(20, 1) == "=B2+B3"
wb.undo()
assert raw(12, 5) is None

# dropping on cells that have something: asked first; No leaves everything as it was
g.select(2, 2, 3, 2)
p0 = border_left(2, 2, 3, 2)
dst = QPoint(g.cell_rect(2, 4).center().x() - (g.cell_rect(2, 2).center().x() - p0.x()), g.cell_rect(2, 4).center().y())
answer[0] = QMessageBox.StandardButton.No
asked.clear()
drag(p0, dst)
assert asked and raw(2, 2) == 22.0 and raw(2, 4) == 24.0, (asked, raw(2, 2), raw(2, 4))
answer[0] = QMessageBox.StandardButton.Yes
drag(p0, dst)
assert raw(2, 4) == 22.0 and raw(3, 4) == 32.0 and raw(2, 2) is None
wb.undo()
assert raw(2, 4) == 24.0 and raw(2, 2) == 22.0

# a click on the border is just a click: it selects the cell; a drag inside the block still selects
g.select(2, 2, 2, 2)
QTest.mouseClick(g.viewport(), LEFT, NO, border_left(2, 2, 2, 2))
assert raw(2, 2) == 22.0 and g.sel() == (2, 2, 2, 2), g.sel()
g.select(1, 1, 1, 1)
drag(g.cell_rect(4, 1).center(), g.cell_rect(6, 3).center())
assert g.sel() == (4, 1, 6, 3), g.sel()
print("OK sheets drag")
os._exit(0)
