"""Exactly one ribbon tool button is lit in a sketch, whichever kinds of tool (plain buttons like Spline / Point, drop-downs like Select / Line)
you switch between; Esc back to Select clears the rest."""
import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp(prefix="opara_ud_")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "shared")]
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_model as pm, pm_app
w = pm_app.MainWindow(); ed = w.ed; ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True); w.sel_plane = "Front"; w.command("sketch")
def lit():
    return [k for k, b in w.act.items() if k.startswith("tool_") and b.isChecked()] + [("menu", i) for i, b in enumerate(w.menu_btns) if b.isChecked()]
tools = ["select", "line", "spline", "point", "rect_corner", "circle", "arc_3pt", "slot_straight", "spline", "line", "point", "select", "spline"]
for a in tools:
    for b in tools:
        w.set_tool(a); w.set_tool(b)
        assert ed.tool == b and len(lit()) == 1, (a, b, ed.tool, lit())
w.set_tool("spline"); ed.cancel()                       # Esc with nothing pending goes back to Select
assert ed.tool == "select" and len(lit()) == 1 and "tool_spline" not in lit(), lit()
print("OK tool highlight")
os._exit(0)
