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
linked = [n for n, _v, g in names if g == "linked"]
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
