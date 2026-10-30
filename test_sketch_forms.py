import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se, unitctl
w = pm_app.MainWindow(); ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.doc.params = {"Gap": "12", "Half": "Gap/2"}; w.sel = None; w.update_all(fit=True)
w.sel_plane = "Front"; w.command("sketch")
# the evaluator: numbers, globals, formulas, units, errors
assert ed.eval_field("5", "Radius (mm)") == (5.0, None)
v, e = ed.eval_field("Gap", "Radius (mm)"); assert v == 12 and e == "Gap", (v, e)
v, e = ed.eval_field("Half + 1", "Step (mm)"); assert v == 7 and e == "Half + 1", (v, e)
v, e = ed.eval_field("1 in", "Step (mm)"); assert abs(v - 25.4) < 1e-9 and e is None
try: ed.eval_field("Nope*2", "Step (mm)"); raise SystemExit("unknown name accepted")
except ValueError: pass
# an offset typed as a global stays linked to it
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
w.set_tool("rect_corner")
for uv in [(-20, -10), (20, 10)]: ed.press(*px(*uv)); ed.release(*px(*uv))
ed.reset_tool("select"); ed.sel = [k for k in ed.keys() if k[0] == "ln"]
def form(parent, title, fields, checks=(), evaluator=None, names=None):
    v, e = evaluator("Half", fields[0][0]); se.LAST_EXPRS[:] = [e]; return [v], [False, True, True]
se.ask_form = form
ed.command_offset()
names = [n for n, p in ed.m.params.items() if p.get("expr") == "Half"]
assert names, ed.m.params
w.doc.params["Gap"] = "20"; w.doc.rebuild()
print("OK")
n = names[0]
print("offset symbol now", ed.m.param_values().get(n), w.doc.models and [m.param_values().get(n) for m in w.doc.models.values()])
