"""The faded preview follows what is typed in the panel of the last feature (Boss / Cut / Revolve ... number boxes): about a fifth of a second after the last key, with ONE step
to undo for the whole edit; half-typed text waits; typing the old value back leaves nothing to undo; a feature whose panel is not previewed still waits for Enter.
python test_extrude_live.py"""
import faulthandler
faulthandler.dump_traceback_later(170, exit=True)
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
os.environ["OPARA_NO_UPDATE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit
app = QApplication([])
import pm_app
import pm_model as pm
import sk_tools as sk
import suggest
suggest.attach = lambda *a, **k: None          # (the name suggestions are not under test; their pop-up takes the focus on this test platform)

FAILS = []


def ok(cond, text):
    print(("ok   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


w = pm_app.MainWindow()
w.show()
app.processEvents()
d = w.doc
d.features.clear()
d.rebuild()
w.update_all()
m = sk.new_model()
sk.add_rect_corner(m, (-5, -5), (5, 5))
sf = d.add(pm.new_feature("sketch", plane={"base": "Front"}, model=m.to_json()))
d.rebuild()
w.sel = sf["id"]
w.update_all()
w.command("extrude")
fe = w.doc.features[-1]


def box():
    return next(e for e in w.props.findChildren(QLineEdit))


def pv():
    info = w.preview_info()
    return None if info is None else sum(s.volume for s, _c in info["parts"])


def type_text(text, wait=450):
    e = box()
    e.setFocus()
    QTest.keyClicks(e, text)
    if wait:
        QTest.qWait(wait)


ok(w.preview_feature() is fe and abs(pv() - 1000) < 1e-6, f"clicking Extrude previews at once (10 mm deep: {pv():.0f} mm3)")
n0 = len(w.undo)
e = box()
e.setFocus()
e.selectAll()
QTest.keyClicks(e, "25")
ok(fe["depth"] == "10" and abs(pv() - 1000) < 1e-6, "right after the key nothing has changed yet (a short pause first: not a rebuild per key)")
QTest.qWait(450)
ok(fe["depth"] == "25" and abs(pv() - 2500) < 1e-6, f"after the pause the preview shows 25 mm ({pv():.0f} mm3)")
ok(len(w.undo) == n0 + 1, "one undo step was made for the edit")
ok(box() is e and e.hasFocus() and e.text() == "25", "the box kept its focus and its text (the panel was not rebuilt under the hand)")
type_text("+")
ok(fe["depth"] == "25" and abs(pv() - 2500) < 1e-6, "half-typed '25+' waits for the rest: the preview stays at 25")
type_text("5")
ok(fe["depth"] == "25+5" and abs(pv() - 3000) < 1e-6, f"'25+5' = 30 mm ({pv():.0f} mm3)")
ok(len(w.undo) == n0 + 1, "still one undo step")
QTest.keyClick(box(), Qt.Key.Key_Return)
QTest.qWait(50)
ok(fe["depth"] == "25+5" and len(w.undo) == n0 + 1 and abs(w.doc.solid.volume - 3000) < 1e-6, "Enter keeps it (no second undo step); the part itself is 3000 mm3")
w.do_undo()
fe2 = w.doc.features[-1]
ok(fe2["kind"] == "extrude" and fe2["depth"] == "10", f"one Undo takes the whole edit back ({fe2['depth']})")

def enter():
    QTest.keyClick(box(), Qt.Key.Key_Return)
    QTest.qWait(50)


def put(text, wait=450):
    """Text into the box as if typed (a user sees the name suggestions of a formula box popping up, which a test platform answers with a focus change)."""
    e = box()
    e.setFocus()
    e.setText(text)
    e.textEdited.emit(text)
    QTest.qWait(wait)


# ---- a name of a global works too, and a name that does not exist yet waits
w.doc.params["Height"] = "40"
w.update_all()
QTest.qWait(80)                                                  # (a rebuilt panel is shown once the event loop has run)
n_ = len(w.undo)
put("Hei")
ok(w.doc.features[-1]["depth"] == "10" and len(w.undo) == n_, "'Hei' is not a name: nothing changes")
put("Height")
ok(w.doc.features[-1]["depth"] == "Height" and abs(pv() - 4000) < 1e-6 and len(w.undo) == n_ + 1, f"'Height' is the global (40 mm: {pv():.0f} mm3), one step")
enter()

# ---- typing the old value back: nothing to undo
n1 = len(w.undo)
put("7")
ok(w.doc.features[-1]["depth"] == "7" and len(w.undo) == n1 + 1, "7 mm: one step")
put("Height")
enter()
ok(w.doc.features[-1]["depth"] == "Height" and abs(pv() - 4000) < 1e-6, "typed back to what it was")
ok(len(w.undo) == n1, f"and the undo step of the round trip was dropped ({len(w.undo)} vs {n1})")

# ---- Enter before the pause is over: the same result, one step
n2 = len(w.undo)
e = box()
e.setFocus()
e.selectAll()
QTest.keyClicks(e, "12")
QTest.keyClick(e, Qt.Key.Key_Return)
QTest.qWait(450)
ok(w.doc.features[-1]["depth"] == "12" and len(w.undo) == n2 + 1 and abs(pv() - 1200) < 1e-6, "Enter at once applies it, one step")

# ---- not the last feature: no preview, so no live change - it waits for Enter as before
sf2 = w.doc.add(pm.new_feature("sketch", plane={"base": "Top"}, model=m.to_json()))
w.doc.rebuild()
w.sel = w.doc.features[1]["id"]
w.left.setCurrentIndex(1)
w.update_all()
ok(w.preview_feature() is None, "(an earlier feature is not previewed)")
n3 = len(w.undo)
e = box()
e.setFocus()
e.selectAll()
QTest.keyClicks(e, "33")
QTest.qWait(450)
ok(w.doc.features[1]["depth"] == "12" and len(w.undo) == n3, "so typing changes nothing until Enter")
QTest.keyClick(e, Qt.Key.Key_Return)
QTest.qWait(50)
ok(w.doc.features[1]["depth"] == "33" and len(w.undo) == n3 + 1, "Enter applies it, one step")

print("FAILED:" if FAILS else "ALL PASSED", FAILS)
sys.exit(1 if FAILS else 0)
