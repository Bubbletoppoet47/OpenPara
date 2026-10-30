import faulthandler; faulthandler.dump_traceback_later(150, exit=True)
import os, tempfile, math
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
app = QApplication([])
import pm_app, pm_model as pm, suggest, sk_tools as sk, sketcher_core as sc
w = pm_app.MainWindow(); d = w.doc
d.params.update({"Width": "40", "Height": "Width/2"}); w.update_all()
names = {n: (v, g) for n, v, g in suggest.names_of(d)}
assert names["Width"] == ("40 mm", "global") and names["Height"][0] == "20 mm", names["Width"]
assert "min" in names and names["min"][1] == "function"
# a box with the list: typing a prefix offers the matching globals, choosing one replaces the word
e = QLineEdit(); e.show()
s = suggest.attach(e, w.suggest_names)
e.setText("2*Wi"); e.setCursorPosition(4); s.update(False)
assert s.comp.completionCount() == 1 and s.comp.completionModel().index(0, 0).data(suggest.NAME_ROLE) == "Width", s.comp.completionCount()
s.chosen(s.comp.completionModel().index(0, 0)); assert e.text() == "2*Width", e.text()
e.setText("Width/2+H"); e.setCursorPosition(9); s.update(False)
s.chosen(s.comp.completionModel().index(0, 0)); assert e.text() == "Width/2+Height", e.text()
# an empty box offers everything (globals first)
e.setText(""); s.update(True); assert s.comp.completionCount() >= 2 + len(suggest.FUNCS) - 1
assert s.comp.completionModel().index(0, 0).data(suggest.NAME_ROLE) in ("Height", "Width")
# a digit or operator at the end offers nothing
e.setText("2*"); e.setCursorPosition(2); s.update(False); assert not s.comp.popup().isVisible()
# the feature boxes have it
sid = next(f["id"] for f in d.features if f["kind"] == "sketch")
w.sel = sid; w.show_props()
# Globals table and the sketch table have a delegate
assert w.gtab.itemDelegateForColumn(1).__class__.__name__ == "SuggestDelegate"
assert w.cfg_panel.table.itemDelegate().__class__.__name__ == "SuggestDelegate"
# circular pattern: horizontal / vertical are not repeated, the other relations are
def hv(m): return [c for c in m.cons if c["type"] in ("horizontal", "vertical")]
m = sk.new_model(); sk.add_rect_corner(m, (0, 0), (40, 20)); sk.solve_model(m)
n0 = len(hv(m)); assert n0 >= 4
keys = [("ln", i) for i in m.lns]
sk.circular_pattern(m, keys, 2, 30, 100, 100); sk.solve_model(m)
assert len(hv(m)) == n0, "a circular pattern must not repeat horizontal / vertical"
rep = sk.solve_model(m); assert rep.ok and not rep.conflicts, rep.messages
m = sk.new_model(); sk.add_rect_corner(m, (0, 0), (40, 20)); sk.solve_model(m)
sk.linear_pattern(m, [("ln", i) for i in m.lns], 1, 100, 0); assert len(hv(m)) == 2 * n0      # a translation keeps them
# mirror about a tilted line drops them, about a vertical line keeps them
def mirror_hv(p0, p1):
    m = sk.new_model(); sk.add_rect_corner(m, (0, 0), (40, 20))
    rect = [("ln", i) for i in m.lns]
    a, b = m.add_point(*p0), m.add_point(*p1); ax = m.add_line(a, b)
    base = len(hv(m)); sk.mirror(m, rect, ax); return len(hv(m)) - base
assert mirror_hv((100, -50), (160, 90)) == 0
assert mirror_hv((100, -50), (100, 90)) == 4
print("OK")
# the real dialogs open with the list attached and return what was typed
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog
import sketch_edit as se
def drive(text):
    def go():
        dlg = next(x for x in app.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible())
        le = dlg.findChildren(QLineEdit)[0]
        assert getattr(le, "children")() and any(isinstance(c, suggest.Suggest) for c in le.children()), "no suggestion list"
        le.setText(text)
        from PyQt6.QtWidgets import QDialogButtonBox as B
        dlg.findChildren(B)[0].button(B.StandardButton.Ok).click()
    QTimer.singleShot(200, go)
drive("Width/4"); assert se.ask_dim(w, "Dimension", "5", [], names=w.suggest_names) == "Width/4"
drive("Height"); r = se.ask_form(w, "Move", [("Move X (mm)", 0.0)], evaluator=lambda t, l: (float(d.values.get(t, 0)), t), names=w.suggest_names)
assert r[0] == [20.0], r
print("DIALOGS OK")
