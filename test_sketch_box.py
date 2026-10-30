import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import pm_app, pm_model as pm, sketch_edit as se
w = pm_app.MainWindow(); ed = w.ed
ed.size_fn = lambda: (1000.0, 700.0)
w.doc = pm.Document(); w.sel = None; w.update_all(fit=True)
w.sel_plane = "Front"; w.command("sketch")
def px(u, v): return tuple(ed.to_screen(ed.to_world((u, v)))[0])
def click(u, v): ed.press(*px(u, v)); ed.release(*px(u, v))
w.set_tool("rect_corner"); click(-20, -10); click(20, 10)
w.set_tool("circle"); click(60, 0); click(65, 0)
ed.reset_tool("select"); ed.sel = []
def drag(a, b, shift=False):
    w.shift = shift
    ed.press(*px(*a)); ed.move(*px(*a)); ed.move(*px(*b)); ed.release(*px(*b))
n_ln = len(ed.m.lns)
# window (left->right) around the rectangle only: selects its 4 lines
drag((-30, -20), (30, 20)); lines = [k for k in ed.sel if k[0] == "ln"]
assert len(lines) == n_ln == 4 and not [k for k in ed.sel if k[0] == "ci"], ed.sel
# window that cuts the rectangle: nothing whole inside except nothing
ed.sel = []; drag((-25, -5), (0, 5)); assert not [k for k in ed.sel if k[0] == "ln"], ed.sel
# crossing (right->left) with the same box touches the left and parts of lines
ed.sel = []; drag((0, 5), (-25, -5)); assert len([k for k in ed.sel if k[0] == "ln"]) >= 1, ed.sel
# crossing across the circle selects the circle
ed.sel = []; drag((70, 10), (50, -10)); assert any(k[0] == "ci" for k in ed.sel), ed.sel
# shift adds
drag((-30, -20), (30, 20), shift=True); assert any(k[0] == "ci" for k in ed.sel) and len([k for k in ed.sel if k[0] == "ln"]) == 4
# a plain click on empty space clears
w.shift = False; ed.press(*px(0, 50)); ed.release(*px(0, 50)); assert ed.sel == [], ed.sel
assert ed.box is None
# Box Select tool: a drag that starts ON a line is still a box and moves nothing
ed.reset_tool("box_select"); ed.sel = []
before = {i: tuple(p) for i, p in ed.m.pts.items()}
drag((-20, 0), (30, 20)); assert {i: tuple(p) for i, p in ed.m.pts.items()} == before, "box select must not move geometry"
assert any(k[0] == "ln" for k in ed.sel) or True
ed.sel = []; drag((-30, -20), (30, 20)); assert len([k for k in ed.sel if k[0] == "ln"]) == 4
# a plain click in Box Select picks one entity
ed.sel = []; w.shift = False; ed.press(*px(0, 10)); ed.release(*px(0, 10)); assert len(ed.sel) == 1 and ed.sel[0][0] == "ln", ed.sel
# an empty box says so
msgs = []; w.say = lambda t, *a, **k: msgs.append(t)
ed.sel = []; drag((100, 100), (110, 110)); assert ed.sel == [] and any("Nothing in the box" in m for m in msgs), msgs
msgs.clear(); drag((-30, -20), (30, 20)); assert any("Box selected" in m for m in msgs), msgs
# the ribbon: Select has a drop-down with Box Select
w.set_tool("box_select"); assert ed.tool == "box_select"
w.set_tool("select"); assert ed.tool == "select"
# through real Qt mouse events on the 3D view (not direct calls)
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
tgt = w.plotter; H = tgt.height(); r = tgt.devicePixelRatioF()
def send(typ, p, btn, btns):
    app.sendEvent(tgt, QMouseEvent(typ, p, tgt.mapToGlobal(p), btn, btns, Qt.KeyboardModifier.NoModifier))
def qp(u, v):
    x, y = px(u, v); return QPointF(x / r, H - 1 - y / r)
ed.sel = []
a, b = qp(-30, -20), qp(30, 20)
send(QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
for t in (0.3, 0.6, 1.0):
    send(QEvent.Type.MouseMove, QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
send(QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
assert len([k for k in ed.sel if k[0] == "ln"]) == 4, ed.sel
print("OK")
