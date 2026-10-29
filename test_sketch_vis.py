import faulthandler; faulthandler.dump_traceback_later(120, exit=True)
import os, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["OPARA_USER_DIR"] = tempfile.mkdtemp()
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
app = QApplication([])
import pm_app, pm_model as pm, sk_tools as sk
w = pm_app.MainWindow(); d = w.doc
sid = next(f["id"] for f in d.features if f["kind"] == "sketch"); f = d.feature(sid)
# a second sketch no feature uses (on by default)
s2 = d.add(pm.new_feature("sketch", plane={"base": "Front"})); d.rebuild(); m = d.models[s2["id"]]
sk.add_rect_corner(m, (0, 0), (10, 10)); sk.solve_model(m); d.store_sketch(s2["id"]); w.update_all()
def shown(): return {x["id"]: w.sketch_shown(x) for x in d.features if x["kind"] == "sketch"}
def item(fid):
    def walk(it):
        if (it.data(0, Qt.ItemDataRole.UserRole) or (None, None))[1] == fid: return it
        for i in range(it.childCount()):
            r = walk(it.child(i))
            if r is not None: return r
    for i in range(w.tree.topLevelItemCount()):
        r = walk(w.tree.topLevelItem(i))
        if r is not None: return r
w.set_show("sketches", True)
assert shown()[s2["id"]] and not shown()[sid]                      # defaults: the used sketch is off, the free one on
# tick the used sketch's checkbox -> it is drawn, and stays checked after a refresh
item(sid).setCheckState(0, Qt.CheckState.Checked); assert f["show"] is True and shown()[sid]
w.refresh_tree(); assert item(sid).checkState(0) == Qt.CheckState.Checked
# select it, then untick: it must really go
w.sel = sid
item(sid).setCheckState(0, Qt.CheckState.Unchecked)
assert f["show"] is False and not shown()[sid], "a selected sketch must still obey its checkbox"
w.refresh_tree(); assert item(sid).checkState(0) == Qt.CheckState.Unchecked, "the checkbox must not snap back"
# the master switch off hides everything, even the selected one and ticked ones
item(sid).setCheckState(0, Qt.CheckState.Checked)
w.sel = s2["id"]
w.set_show("sketches", False)
assert not any(shown().values()), shown()
w.refresh_tree()
assert item(sid).checkState(0) == Qt.CheckState.Checked            # each sketch keeps its own checkbox
# master on again: the checkboxes decide
w.set_show("sketches", True)
assert shown()[sid] and shown()[s2["id"]]
item(s2["id"]).setCheckState(0, Qt.CheckState.Unchecked); assert not shown()[s2["id"]] and shown()[sid]
# the sketch being edited is always drawn by the editor
w.enter_sketch(sid); assert w.sketch_shown(f); w.leave_sketch()
import icons
assert icons.icon("Reference\nGeometry") is not None
print("SKETCH VISIBILITY OK")
