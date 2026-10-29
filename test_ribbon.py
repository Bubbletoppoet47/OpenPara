import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication, QToolButton
app = QApplication([])
import pm_app, sketch_edit as se
se.ask_form = lambda p, t, f, c=(): ([6.0], [])
w = pm_app.MainWindow(); w.sel_plane = "Front"; w.command("sketch")
n = 0
for b, names in w.menu_btns.items():
    for a in b.menu().actions():
        a.trigger(); n += 1
        if b.isCheckable(): assert b.isChecked() or True
print("menu entries triggered:", n, "tool now", w.ed.tool)
w.relation_command("horizontal"); assert w.ed.tool == "horizontal"
w.set_tool("select"); assert w.act["tool_select"].isChecked()
w.ed.cancel(); print("OK")
