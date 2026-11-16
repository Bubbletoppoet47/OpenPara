"""Systems and Controls tab (dev_addons/controls): dropdown sections, the Transfer function section typed into live, files, plot, manifest."""
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
from PyQt6.QtWidgets import QApplication

app = QApplication([])
import controls_tab as T

t = T.make_tab()
t.resize(1300, 800)
t.show()
app.processEvents()
tf = t.section("transfer_function")
assert tf is not None and t.section("nope") is None

# ---- the section is open at the start and its page is showing ----------------------------------------------------------------------------
assert t.drops[0].is_open() and t.pages.currentWidget() is tf.results and tf.inputs.isVisible()
assert "Type the numerator" in tf.text.toPlainText() and tf.analysis is None and not t.is_dirty()
t.drops[0].set_open(False)
assert not tf.inputs.isVisible()
t.drops[0].set_open(True)
assert tf.inputs.isVisible()

# ---- typing the book example gives the book answer ---------------------------------------------------------------------------------------
tf.num.setText("2s+3")
assert "denominator" in tf.msg.text().lower() or tf.analysis is None          # half typed: a gentle message, no crash
tf.den.setText("s^2+3s+2")
a = tf.analysis
assert a is not None and abs(a.gain - 2.0) < 1e-12 and abs(a.dc - 1.5) < 1e-12
out = tf.text.toPlainText()
assert "2 (s + 1.5)" in out and "(s + 1)(s + 2)" in out and "Zeros (roots of the numerator):   -1.5" in out and "G(0) = 3 / 2 = 1.5" in out
assert tf.msg.text() == "" and [round(z.real, 9) for z in tf.plot.zeros] == [-1.5] and sorted(round(p.real, 9) for p in tf.plot.poles) == [-2.0, -1.0]
tf.plot.grab()                                                                  # painting must not raise
t.grab()

# ---- mistakes are explained, not crashed on ---------------------------------------------------------------------------------------------
tf.den.setText("s^2+3s+")
assert tf.analysis is None and tf.msg.text().startswith("Denominator:") and tf.text.toPlainText() == "" and not tf.plot.poles
tf.num.setText("2s@3")
assert tf.msg.text().startswith("Numerator:") and "@" in tf.msg.text()
tf.num.setText("0")
tf.den.setText("s+1")
assert "numerator is zero" in tf.msg.text()
tf.num.setText("1")
tf.den.setText("0")
assert "denominator is zero" in tf.msg.text()
tf.plot.grab()

# ---- the examples ---------------------------------------------------------------------------------------------------------------------------
assert tf.ex.count() == 1 + len(tf.EXAMPLES)
for i in range(1, tf.ex.count()):
    tf.load_example(i)
    assert tf.analysis is not None and tf.msg.text() == "", tf.ex.itemText(i)
    t.grab()
tf.load_example(1)
assert tf.num.text() == "2s+3" and tf.den.text() == "s^2+3s+2" and abs(tf.analysis.dc - 1.5) < 1e-12
tf.load_example(3)
assert "(s² + 2s + 5)" in tf.text.toPlainText() and len(tf.plot.poles) == 3
tf.load_example(2)
assert "infinite" in tf.text.toPlainText() and "(repeated 2 times)" in tf.text.toPlainText()
tf.load_example(4)
assert tf.analysis.stability == "unstable"
assert t.is_dirty()

# ---- files: save, reopen, same answer ------------------------------------------------------------------------------------------------------
tf.load_example(1)
path = os.path.join(UD, "book.opctl")
t.path = path
t.save()
assert os.path.isfile(path) and not t.is_dirty()
d = json.load(open(path))
assert d["format"] == "openpara-controls" and d["sections"]["transfer_function"] == {"num": "2s+3", "den": "s^2+3s+2"}
t2 = T.make_tab(path)
assert t2.title() == "book.opctl" and not t2.is_dirty() and abs(t2.section("transfer_function").analysis.dc - 1.5) < 1e-12
t2.new()
assert t2.section("transfer_function").num.text() == "" and t2.path is None and t2.title() == "Controls"
t2.section("transfer_function").num.textEdited.emit("x")
assert t2.is_dirty()

# ---- the plot's view box includes the origin and every root ----------------------------------------------------------------------------
pl = T.PoleZeroPlot()
pl.set_roots([complex(-1.5, 0)], [complex(-1, 2), complex(-1, -2), complex(-3, 0)])
x0, x1, y0, y1 = pl.view_box()
assert x0 < -3 and x1 > 0 and y0 < -2 and y1 > 2
assert T.nice_step(10) >= 1

# painting at silly sizes, with and without roots, must never raise (an error in a paint event closes the program)
for size in ((1, 1), (10, 5), (50, 50), (300, 260), (2000, 100), (80, 900)):
    for roots in (([], []), ([complex(-1.5, 0)], [complex(-1, 0), complex(-2, 0)]), ([], [complex(0, 0)]), ([complex(1e6, 0)], [complex(-1e-6, 1e-6)])):
        pl.set_roots(*roots)
        pl.setMinimumSize(0, 0)
        pl.resize(*size)
        pl.grab()

# ---- the add-on is described for the app -------------------------------------------------------------------------------------------------------
spec = json.load(open(os.path.join(HERE, "dev_addons", "controls", "addon.json")))
assert spec["name"] == "Systems and Controls" and spec["status"] == "workshopping"
tab = spec["tabs"][0]
assert tab["kind"] == "controls" and tab["module"] == "controls_tab" and tab["factory"] == "make_tab" and tab["file_types"] == [".opctl"]
assert not os.path.exists(os.path.join(HERE, "dev_addons", "dynamics"))
print("PASS controls tab")
