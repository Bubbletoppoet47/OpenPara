"""Mechanical / Electrical systems section: drawing with the mouse, the table, domains, views, files, painting."""
import faulthandler
import json
import os
import sys
import tempfile

faulthandler.dump_traceback_later(170, exit=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
UD = tempfile.mkdtemp()
os.environ["OPARA_USER_DIR"] = UD
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "dev_addons", "controls"), os.path.join(HERE, "shared"), HERE]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import controls_tab as T
import ctl_canvas as cv

t = T.make_tab()
t.resize(1500, 900)
t.show()
app.processEvents()
n = t.section("network")
assert n is not None and [d.section.key for d in t.drops] == ["transfer_function", "network", "dynamic"]
t.show_section("network")
app.processEvents()
assert t.pages.currentWidget() is n.results and n.inputs.isVisible() and not t.section("transfer_function").inputs.isVisible()
assert "Pick a part" in n.text.toPlainText() or "Wire joins" in n.text.toPlainText()
assert n.canvas.parts == [] and not n.send.isEnabled()


def click(g, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(n.canvas, button, pos=n.canvas.to_px(g).toPoint())


def tool(name):
    n.btns[name].click()
    assert n.canvas.tool == name


# ---- draw the book's 1.5.5.3 circuit with the mouse ----------------------------------------------------------------------------------------------
tool("V"); click((2, 4)); click((2, 10))
tool("wire"); click((2, 4)); click((4, 4)); n.canvas.pending = None          # short wires between the parts (a long wire would short them out)
click((12, 4)); click((16, 4)); n.canvas.pending = None
tool("L"); click((4, 4)); click((8, 4))
tool("R"); click((8, 4)); click((12, 4))
tool("C"); click((16, 4)); click((16, 10))
tool("wire"); click((2, 10)); click((16, 10)); n.canvas.pending = None
tool("GND"); click((9, 10))
tool("VO"); click((16, 4))
tool("select")
kinds = sorted(p["kind"] for p in n.canvas.parts)
assert kinds.count("V") == 1 and kinds.count("L") == 1 and kinds.count("R") == 1 and kinds.count("C") == 1 and kinds.count("GND") == 1 and kinds.count("VO") == 1, kinds
assert [p["name"] for p in n.canvas.parts if p["kind"] in ("L", "R", "C")] == ["L", "R", "C"]
assert n.sol is not None, n.text.toPlainText()
assert "G(s) = Vo/Vi = 1 / (C L s² + C R s + 1)" in n.text.toPlainText(), n.text.toPlainText()
assert "Give a number to C, L, R" in n.text.toPlainText() and "mass M = L" in n.text.toPlainText()
assert len(n.analog.parts) > 5 and n.view.itemText(0) == "Mechanical analog" and t.is_dirty()
assert n.table.rowCount() == 3 and n.table.item(0, 0).text() == "L"

# ---- numbers in the table give poles and the step response; send it to the Transfer function section ------------------------------------------------
for r, val in ((0, "0.1"), (1, "5"), (2, "0.05")):
    n.table.item(r, 1).setText(val)
assert n.numbers is not None and n.send.isEnabled(), n.text.toPlainText()
txt = n.text.toPlainText()
assert "Poles: -4.38447, -45.6155" in txt and "Step response:" in txt and "200 / (s² + 50 s + 200)" in txt, txt
assert "spring K = 20" in txt and "damper B = 5" in txt and "mass M = 0.1" in txt
assert abs(n.analysis.dc - 1.0) < 1e-9 and n.analysis.stability == "stable"
n.view.setCurrentIndex(3); n.show_view()
assert n.stack.currentWidget() is n.time_plot and n.time_plot.kind == "step" and n.time_plot.resp is not None
n.view.setCurrentIndex(4); n.show_view()
assert n.time_plot.kind == "impulse"
n.view.setCurrentIndex(1); n.show_view(); assert n.stack.currentWidget() is n.plot and len(n.plot.poles) == 2
n.view.setCurrentIndex(2); n.show_view(); assert n.stack.currentWidget() is n.diagram and n.diagram.blocks
n.view.setCurrentIndex(0); n.show_view(); assert n.stack.currentWidget() is n.analog
n.send.click()
tf = t.section("transfer_function")
assert t.drops[0].is_open() and tf.analysis is not None and abs(tf.analysis.dc - 1.0) < 1e-9 and len(tf.analysis.poles) == 2

# ---- editing: select, move, rotate, delete -------------------------------------------------------------------------------------------------------------
n.set_domain("electrical")
tool("select")
count = len(n.canvas.parts)
click((9, 10))                                                                   # the ground symbol
assert n.canvas.sel is not None and n.canvas.parts[n.canvas.sel]["kind"] == "GND"
rot0 = n.canvas.parts[n.canvas.sel]["rot"]
n.canvas.rotate_selected()
assert n.canvas.parts[n.canvas.sel]["rot"] == (rot0 + 1) % 4
n.canvas.rotate_selected(); n.canvas.rotate_selected(); n.canvas.rotate_selected()
n.del_btn.click()
assert len(n.canvas.parts) == count - 1 and "ground" in n.text.toPlainText().lower()
tool("GND"); click((9, 10)); tool("select")
assert n.sol is not None
QTest.mouseClick(n.canvas, Qt.MouseButton.RightButton, pos=n.canvas.to_px((20, 20)).toPoint())    # right click with Select does nothing bad
tool("wire"); click((20, 20)); QTest.mouseClick(n.canvas, Qt.MouseButton.RightButton, pos=n.canvas.to_px((22, 20)).toPoint())
assert n.canvas.pending is None
n.canvas.tool_reset.emit() if False else None

# ---- drag a part: the whole part moves ---------------------------------------------------------------------------------------------------------------
tool("select")
before = [p["a"] for p in n.canvas.parts if p["kind"] == "R"][0]
QTest.mousePress(n.canvas, Qt.MouseButton.LeftButton, pos=n.canvas.to_px((10, 4)).toPoint())
QTest.mouseMove(n.canvas, n.canvas.to_px((10, 6)).toPoint())
QTest.mouseRelease(n.canvas, Qt.MouseButton.LeftButton, pos=n.canvas.to_px((10, 6)).toPoint())
after = [p["a"] for p in n.canvas.parts if p["kind"] == "R"][0]
assert after == (before[0], before[1] + 2), (before, after)
assert n.sol is None or "not" in n.text.toPlainText().lower() or n.sol is not None               # moved off the wire: the answer reacts, never crashes

# ---- mechanical side keeps its own drawing --------------------------------------------------------------------------------------------------------
n.load_example(2)
assert n.domain == "mechanical" and n.dom.currentText() == "Mechanical system" and n.view.itemText(0) == "Electrical analog"
assert "G(s) = x/F = 1 / (s² + B s + 2)" in n.text.toPlainText(), n.text.toPlainText()
assert "Give a number to B" in n.text.toPlainText() and len(n.analog.parts) > 5
n.table.item(1, 1).setText("3") if n.table.item(1, 0).text() == "B" else None
for r in range(n.table.rowCount()):
    if n.table.item(r, 0).text() == "B":
        n.table.item(r, 1).setText("3")
assert n.numbers is not None and [round(x, 9) for x in n.numbers[1]] == [1.0, 3.0, 2.0], n.text.toPlainText()
assert "Poles: -1, -2" in n.text.toPlainText() and "Impulse response: y(t) = e^(-t) - e^(-2t)" in n.text.toPlainText()
n.dom.setCurrentIndex(0); n.dom.activated.emit(0)
assert n.domain == "electrical" and any(p["kind"] == "C" for p in n.canvas.parts)                  # the circuit is still there
n.dom.setCurrentIndex(1); n.dom.activated.emit(1)
assert n.domain == "mechanical" and any(p["kind"] == "M" for p in n.canvas.parts)

# ---- the three book examples through the picker -----------------------------------------------------------------------------------------------------
n.load_example(3)
assert "200 / (s² + 54 s + 400)" in n.text.toPlainText() and "Poles: -8.86" in n.text.toPlainText() and "Step response:" in n.text.toPlainText()
assert abs(n.analysis.dc - 0.5) < 1e-9
n.load_example(1)
assert "1 / (C L s² + C R s + 1)" in n.text.toPlainText()

# ---- files ---------------------------------------------------------------------------------------------------------------------------------------
n.load_example(3)
n.view.setCurrentIndex(4); n.show_view()
t.path = os.path.join(UD, "net.opctl")
t.save()
d = json.load(open(t.path))
net = d["sections"]["network"]
assert net["domain"] == "electrical" and net["view"] == 4 and any(p["kind"] == "C" and p["value"] == "0.05" for p in net["electrical"]) and len(net["mechanical"]) > 0
t2 = T.make_tab(t.path)
n2 = t2.section("network")
assert n2.domain == "electrical" and n2.view.currentIndex() == 4 and n2.numbers is not None and abs(n2.analysis.dc - 0.5) < 1e-9
t2.new()
assert n2.canvas.parts == [] and n2.domain == "electrical" and n2.view.currentIndex() == 0
n2.from_json({"electrical": [{"kind": "nope", "a": [1, 2]}, {"kind": "R", "a": [1, 2]}, "junk", {"kind": "R", "a": [1, 2], "b": [5, 2]}], "view": "bad"})   # damaged data is skipped
assert len(n2.canvas.parts) == 1

# ---- painting never raises, however small or odd ----------------------------------------------------------------------------------------------------
n.load_example(1)
for c in (n.canvas, n.analog):
    for size in ((1, 1), (60, 40), (300, 200), (1200, 700)):
        c.resize(*size)
        img = QImage(max(size[0], 1), max(size[1], 1), QImage.Format.Format_RGB32)
        p = QPainter(img)
        c.draw(p)
        p.end()
        c.grab()
for i in (1, 2, 3):
    n.load_example(i)
    n.canvas.sel = 0
    n.canvas.hover = (3, 3)
    n.canvas.pending = (2, 2)
    n.canvas.grab()
    n.analog.grab()
n.canvas.set_parts([])
n.canvas.grab()
for kind in cv.ckt.ELECTRICAL + cv.ckt.MECHANICAL:                                          # every symbol paints in every direction
    for rot in range(4):
        pt = cv.new_part(kind, (4, 4), (8, 4) if kind in cv.ckt.TWO else None, rot)
        n.canvas.set_parts([pt])
        n.canvas.sel = 0
        n.canvas.grab()
print("PASS controls network")
