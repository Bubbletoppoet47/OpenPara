"""Linked variables (AS_<config>_<name>): found by typing AS in a formula box, written in braces, and usable in features and part sketches."""
import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pm_model as pm, sk_tools as sk, gsv, suggest
from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtCore import Qt
close = lambda a, b, t=1e-6: abs(a - b) <= t * max(1, abs(a), abs(b))

d = pm.Document()
d.gsv_set("s.gpk", ["Small", "Big"], [{"name": "W", "kind": "length", "role": "driving"}], {"Small": {"W": 60.0}, "Big": {"W": 140.0}})

# ---- the suggestion list: typing AS finds them, first in the list, inserted in braces
names = suggest.names_of(d)
linked = [n for n, _v, g in names if g.startswith("linked")]
assert linked == ["AS_Small_W", "AS_Big_W"] or sorted(linked) == ["AS_Big_W", "AS_Small_W"], linked
app = QApplication.instance() or QApplication([])
e = QLineEdit(); sg = suggest.attach(e, lambda: suggest.names_of(d))
e.setText("2*AS"); e.setCursorPosition(4); sg.update(True)
shown = [sg.comp.completionModel().index(i, 0).data(suggest.NAME_ROLE) for i in range(sg.comp.completionCount())]
assert sorted(shown) == ["AS_Big_W", "AS_Small_W"], shown
sg.chosen(sg.comp.completionModel().index(0, 0))
assert e.text() in ("2*{AS_Big_W}", "2*{AS_Small_W}"), e.text()
e.setText("{AS"); e.setCursorPosition(3); sg.chosen(sg.comp.completionModel().index(0, 0)); assert e.text().count("{") == 1 and e.text().endswith("}"), e.text()

# ---- used in a part sketch dimension (through a sketch symbol) and in features
s = d.add(pm.new_feature("sketch", plane={"base": "Top"})); d.rebuild(); m = d.models[s["id"]]
sk.add_rect_corner(m, (0, 0), (20, 20)); sk.solve_model(m)
ln = next(i for i in sorted(m.lns) if all(abs(m.pts[p][1]) < 1e-9 for p in m.lns[i]))
m.add_param("L", 20.0, False, "{AS_Big_W}/7"); m.add_con("dim_len", [("ln", ln)], value=20.0, name="L", expr="L")
sk.solve_model(m); d.store_sketch(s["id"])
f = d.add(pm.new_feature("extrude", sketch=s["id"], depth="{AS_Small_W}/6")); d.rebuild()
assert d.status[f["id"]] == "ok", d.status
m = d.models[s["id"]]
assert close(m.param_values()["L"], 20.0), m.param_values()
assert close(d.solid.volume, 20 * 20 * 10), d.solid.volume
d.params["Gap"] = "{AS_Big_W} - {AS_Small_W}"; d.rebuild(); assert close(d.values["Gap"], 80)
print("linked variables usable OK")

# ---- a configuration with a space in its name ("Config 1"): the whole name is typed, offered and inserted
d2 = pm.Document()
d2.gsv_set("s.gpk", ["Config 1"], [{"name": "I1", "kind": "length", "role": "driving"}], {"Config 1": {"I1": 3000.0}})
e = QLineEdit(); sg = suggest.attach(e, lambda: suggest.names_of(d2))
e.setText("AS"); e.setCursorPosition(2); sg.update(True)
assert sg.comp.completionCount() == 1
sg.chosen(sg.comp.completionModel().index(0, 0)); assert e.text() == "{AS_Config 1_I1}", e.text()
e.setText("{AS_Config 1"); e.setCursorPosition(len(e.text())); sg.update(True)
assert sg.comp.completionCount() == 1, sg.comp.completionCount()
sg.chosen(sg.comp.completionModel().index(0, 0)); assert e.text() == "{AS_Config 1_I1}", e.text()
s2 = d2.add(pm.new_feature("sketch", plane={"base": "Top"})); d2.rebuild(); m2 = d2.models[s2["id"]]
sk.add_rect_corner(m2, (0, 0), (20, 20)); sk.solve_model(m2); d2.store_sketch(s2["id"])
f2 = d2.add(pm.new_feature("extrude", sketch=s2["id"], depth="{AS_Config 1_I1}/100")); d2.rebuild()
assert d2.status[f2["id"]] == "ok" and close(d2.solid.volume, 20 * 20 * 30), (d2.status, d2.solid.volume)
print("names with spaces OK")

# ---- the drop-down is wide enough for the longest line
e = QLineEdit(); e.resize(80, 24); sg = suggest.attach(e, lambda: suggest.names_of(d2))
e.setText("AS"); e.setCursorPosition(2); sg.update(True)
assert sg.popup_rect().width() > 120, sg.popup_rect()
print("popup width OK")

# ---- the list is as wide as its longest line; the active configuration's variables come first
d3 = pm.Document()
d3.gsv_set("s.gpk", ['120"', 'A very long configuration name'], [{"name": "Pipe_Length", "kind": "length", "role": "driving"}],
           {'120"': {"Pipe_Length": 3000.0}, "A very long configuration name": {"Pipe_Length": 4000.0}})
d3.cfg_apply('120"')
e = QLineEdit(); e.resize(120, 24); e.show(); sg = suggest.attach(e, lambda: suggest.names_of(d3))
e.setText("AS"); e.setCursorPosition(2); sg.update(True)
first = sg.comp.completionModel().index(0, 0).data(suggest.NAME_ROLE); assert first == 'AS_120"_Pipe_Length', first
r = sg.popup_rect(); assert r.width() > 300, r.width()
from PyQt6.QtGui import QFontMetrics
longest = max(QFontMetrics(sg.comp.popup().font()).horizontalAdvance(sg.comp.completionModel().index(i, 0).data()) for i in range(sg.comp.completionCount()))
assert r.width() >= longest, (r.width(), longest)
print("suggestion list width fits OK")
