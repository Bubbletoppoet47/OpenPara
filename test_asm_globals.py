import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, tempfile, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication, QLineEdit
app = QApplication([])
import assembly, asm_model as am, unitctl
w = assembly.AssemblyWindow()
a = w.asm
c1 = a.add_component("/x/a.opp", pos=(0, 0, 0)); c2 = a.add_component("/x/b.opp", pos=(5, 0, 0))
# globals + a position formula
a.params = {"Gap": "10", "Twice": "Gap*2"}
v, e = w.parse_field("Twice + 5", True); assert v == 25 and e == "Twice + 5", (v, e)
v, e = w.parse_field("2 in", True); assert abs(v - 50.8) < 1e-9 and e is None
v, e = w.parse_field("30", True); assert v == 30 and e is None
try: w.parse_field("Nope+1", True); raise SystemExit("unknown accepted")
except ValueError: pass
a.set_expr(f"pos:{c2['id']}:0", "Twice + 5"); w.solve_all()
assert c2["pos"][0] == 25, c2["pos"]
a.params["Gap"] = "20"; w.solve_all(); assert c2["pos"][0] == 45, c2["pos"]     # the global moves it
# a mate value and a pattern field follow too
m = a.add_mate("distance", [{"c": c1["id"], "k": "x"}, {"c": c2["id"], "k": "y"}], value=1.0)
a.set_expr(f"val:{m['id']}", "Gap/2"); a.apply_exprs(); assert m["value"] == 10
a.patterns.append({"id": "P1", "type": "linear", "name": "Pat", "seeds": [c1["id"]], "s1": 3.0, "n1": 2})
a.set_expr("pat:P1:s1", "Gap+1"); a.apply_exprs(); assert a.patterns[0]["s1"] == 21
# saved and reopened
b = am.Assembly.from_json(a.to_json())
assert b.params == a.params and b.exprs == a.exprs
b.params["Gap"] = "4"; b.apply_exprs(); assert b.comp(c2["id"])["pos"][0] == 13 and b.mate(m["id"])["value"] == 2
# the Globals table shows them
w.update_all(); assert w.gtab.rowCount() == 2
# the position box shows the formula
w.sel_comp = c2["id"]; w.show_comp_props()
boxes = [x for x in w.props.findChildren(QLineEdit) if x.text() == "Twice + 5"]
assert boxes, [x.text() for x in w.props.findChildren(QLineEdit)]
boxes[0].setText("Gap + 1"); boxes[0].editingFinished.emit()
assert a.exprs[f"pos:{c2['id']}:0"] == "Gap + 1" and c2["pos"][0] == 21, c2["pos"]
w.sel_comp = c2["id"]; w.show_comp_props()
bx = [x for x in w.props.findChildren(QLineEdit) if x.text() == "Gap + 1"][0]
bx.setText("7"); bx.editingFinished.emit()
assert f"pos:{c2['id']}:0" not in a.exprs and c2["pos"][0] == 7, (a.exprs, c2["pos"])
print("OK")
